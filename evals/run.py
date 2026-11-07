"""Command line for the discovery evals.

    python -m evals.run validate
    python -m evals.run run --system both [--case ID ...] [--repeats 3] [--reviewed-only]
    python -m evals.run score data/evals/runs/<run_id> [...more run dirs]
    python -m evals.run queue

Credentials come from ``.env`` / the environment: CELL_LEDGER_ANTHROPIC_API_KEY (required to
run), CELL_LEDGER_NCBI_API_KEY and CELL_LEDGER_EXA_API_KEY (optional). ``validate``, ``score``
and ``queue`` need none.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from cell_ledger_api.agent.discover import Discoverer
from cell_ledger_api.agent.llm import sdk_turn_runner
from evals.baseline import baseline_fingerprint, run_baseline
from evals.cases import CASES_DIR, Case, Suite, load_suite
from evals.geo_cache import CachedExa, CachedGeoClient
from evals.records import Conditions, RunRecord, git_revision, load_records, write_json
from evals.report import render
from evals.scoring import QUEUE_PATH, score, update_queue
from evals.specialist import run_specialist

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "data/evals/runs"
CACHE_DIR = ROOT / "data/evals/geo-cache"


class EvalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CELL_LEDGER_", env_file=".env", extra="ignore")

    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("CELL_LEDGER_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    anthropic_model: str = "claude-opus-5-5"
    anthropic_effort: str = "medium"
    ncbi_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("CELL_LEDGER_NCBI_API_KEY", "NCBI_API_KEY")
    )
    exa_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("CELL_LEDGER_EXA_API_KEY", "EXA_API_KEY")
    )


def select_cases(suite: Suite, ids: list[str], reviewed_only: bool) -> list[Case]:
    cases = suite.cases
    if ids:
        known = suite.by_id()
        missing = [i for i in ids if i not in known]
        if missing:
            raise SystemExit(f"unknown case ids: {missing}")
        cases = [known[i] for i in ids]
    if reviewed_only:
        cases = [c for c in cases if c.status == "reviewed"]
    if not cases:
        raise SystemExit("no cases selected")
    return cases


async def run_suite(args: argparse.Namespace) -> Path:
    cfg = EvalSettings()
    if cfg.anthropic_api_key is None:
        raise SystemExit("CELL_LEDGER_ANTHROPIC_API_KEY is not set; runs need Claude")
    suite = load_suite(args.cases)
    cases = select_cases(suite, args.case, args.reviewed_only)
    systems = ["specialist", "baseline"] if args.system == "both" else [args.system]
    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or RUNS_DIR / run_id
    out.mkdir(parents=True, exist_ok=True)
    cache_dir = args.geo_cache or CACHE_DIR / run_id
    model = args.model or cfg.anthropic_model
    effort = args.effort or cfg.anthropic_effort
    revision, dirty = git_revision(ROOT)
    started = datetime.now(UTC).isoformat(timespec="seconds")

    import anthropic

    anthropic_client = anthropic.AsyncAnthropic(
        api_key=cfg.anthropic_api_key.get_secret_value(), max_retries=2
    )
    turn = sdk_turn_runner(anthropic_client)
    exa = None
    if cfg.exa_api_key and not args.no_web:
        from exa_py import AsyncExa

        exa = AsyncExa(api_key=cfg.exa_api_key.get_secret_value())
    web_search = not args.no_web
    sem = asyncio.Semaphore(args.concurrency)
    records: list[RunRecord] = []

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30, read=120),
        follow_redirects=True,
        headers={"User-Agent": "cell-ledger-evals"},
    ) as http:
        key = cfg.ncbi_api_key.get_secret_value() if cfg.ncbi_api_key else None
        geo = CachedGeoClient(http, cache_dir, api_key=key)
        cached_exa = CachedExa(exa, cache_dir) if exa is not None else None
        fingerprints = {
            "specialist": Discoverer(
                geo,
                exa=cached_exa,  # type: ignore[arg-type]
                model=model,
                effort=effort,
            ).fingerprint(),
            "baseline": baseline_fingerprint(model, effort, web_search),
        }
        write_json(
            out / "run.json",
            {
                "run_id": run_id,
                "started_at": started,
                "systems": systems,
                "cases": [c.id for c in cases],
                "repeats": args.repeats,
                "model": model,
                "effort": effort,
                "web_search": web_search,
                "exa": exa is not None,
                "geo_cache": str(cache_dir),
                "code_revision": revision,
                "dirty": dirty,
                "suite_sha256": suite.digest(),
                "fingerprints": fingerprints,
            },
        )

        async def one(system: str, case: Case, repeat: int) -> None:
            conditions = Conditions(
                system=system,  # type: ignore[arg-type]
                model=model,
                effort=effort,
                fingerprint=fingerprints[system],
                web_search=(exa is not None) if system == "specialist" else web_search,
                code_revision=revision,
                dirty=dirty,
                geo_cache=str(cache_dir),
                case_sha256=case.digest(),
                suite_sha256=suite.digest(),
                run_id=run_id,
                started_at=datetime.now(UTC).isoformat(timespec="seconds"),
            )
            async with sem:
                if system == "specialist":
                    rec = await run_specialist(
                        case,
                        geo=geo,
                        turn=turn,
                        exa=cached_exa,
                        conditions=conditions,
                        repeat=repeat,
                    )
                else:
                    rec = await run_baseline(
                        case, geo=geo, turn=turn, conditions=conditions, repeat=repeat
                    )
            path = rec.save(out)
            records.append(rec)
            status = rec.error or f"{rec.final_action}, {len(rec.candidates)} candidates"
            print(f"{system:10} {case.id:40} r{repeat}: {status}  -> {path.relative_to(ROOT)}")

        await asyncio.gather(
            *(
                one(system, case, repeat)
                for system in systems
                for case in cases
                for repeat in range(1, args.repeats + 1)
            )
        )
        print(f"GEO cache: {geo.hits} hits, {geo.misses} misses ({cache_dir.relative_to(ROOT)})")

    await anthropic_client.close()
    if exa is not None:
        await exa.aclose()
    write_results(suite, records, out, update_review_queue=not args.no_queue)
    return out


def write_results(
    suite: Suite, records: list[RunRecord], out: Path, *, update_review_queue: bool
) -> dict:
    result = score(suite, records)
    write_json(out / "results.json", result)
    (out / "results.md").write_text(render(result))
    if update_review_queue:
        queued = update_queue(result, records, suite)
        print(
            f"review queue: {len(queued)} candidates await a verdict "
            f"({QUEUE_PATH.relative_to(ROOT)})"
        )
    print(render(result))
    print(f"wrote {out / 'results.json'} and {out / 'results.md'}")
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m evals.run",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="check every case file")
    v.add_argument("--cases", type=Path, default=CASES_DIR)

    r = sub.add_parser("run", help="run cases through the specialist and/or the baseline")
    r.add_argument("--system", choices=["specialist", "baseline", "both"], default="both")
    r.add_argument("--cases", type=Path, default=CASES_DIR)
    r.add_argument("--case", action="append", default=[], help="case id; repeatable")
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--reviewed-only", action="store_true")
    r.add_argument("--model", help="default CELL_LEDGER_ANTHROPIC_MODEL")
    r.add_argument("--effort", help="default CELL_LEDGER_ANTHROPIC_EFFORT")
    r.add_argument(
        "--no-web",
        action="store_true",
        help="no Exa for the specialist, no web search for the baseline",
    )
    r.add_argument("--concurrency", type=int, default=2)
    r.add_argument("--run-id", help="default: UTC timestamp")
    r.add_argument("--out", type=Path, help="default data/evals/runs/<run_id>")
    r.add_argument("--geo-cache", type=Path, help="reuse another run's GEO cache for an exact A/B")
    r.add_argument("--no-queue", action="store_true", help="do not touch evals/review_queue.json")

    s = sub.add_parser("score", help="score saved run directories")
    s.add_argument("run_dirs", type=Path, nargs="+")
    s.add_argument("--cases", type=Path, default=CASES_DIR)
    s.add_argument("--out", type=Path, help="default: the first run dir")
    s.add_argument("--no-queue", action="store_true")

    sub.add_parser("queue", help="list candidates waiting for a human verdict")

    args = p.parse_args(argv)
    if args.cmd == "validate":
        suite = load_suite(args.cases)
        reviewed = sum(c.status == "reviewed" for c in suite.cases)
        for c in suite.cases:
            print(
                f"{c.id:40} {c.expected_action:10} {c.status:9} "
                f"pool={len(c.pool)} positives={len(c.positives())}"
            )
        print(f"{len(suite.cases)} cases valid, {reviewed} reviewed; suite {suite.digest()[:12]}")
        return 0
    if args.cmd == "run":
        asyncio.run(run_suite(args))
        return 0
    if args.cmd == "score":
        suite = load_suite(args.cases)
        records = [rec for d in args.run_dirs for rec in load_records(d)]
        if not records:
            raise SystemExit("no run records found")
        write_results(
            suite, records, args.out or args.run_dirs[0], update_review_queue=not args.no_queue
        )
        return 0
    if args.cmd == "queue":
        queue = json.loads(QUEUE_PATH.read_text()) if QUEUE_PATH.exists() else []
        if not queue:
            print("review queue is empty")
            return 0
        for e in queue:
            print(f"{e['case_id']:40} {e['gse']:12} {', '.join(e['systems']):20} {e['title'][:70]}")
            if e["why"]:
                print(f"{'':40} why: {e['why'][:120]}")
        print(f"{len(queue)} candidates; add each to its case's pool with a verdict, then re-score")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
