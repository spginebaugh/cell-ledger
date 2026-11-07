"""Render a scoring result as Markdown: one table across systems, misses, then every run."""

from __future__ import annotations

from typing import Any


def _pct(r: dict[str, Any] | None) -> str:
    if not r or r.get("value") is None:
        return "n/a"
    return f"{100 * r['value']:.0f}% ({r['n']}/{r['d']})"


def _mean(s: dict[str, Any] | None, fmt: str = ".2f") -> str:
    if not s or s.get("mean") is None:
        return "n/a"
    if s["n"] > 1 and s["min"] != s["max"]:
        return f"{s['mean']:{fmt}} [{s['min']:{fmt}} to {s['max']:{fmt}}]"
    return f"{s['mean']:{fmt}}"


def render(result: dict[str, Any]) -> str:
    systems = list(result["summaries"])
    lines = [
        "# Discovery eval results",
        "",
        f"Generated {result['generated_at']} · suite `{result['suite_sha256'][:12]}` · "
        f"{len(result['cases_scored'])} cases scored",
        "",
        f"Comparison ready: **{result['comparison_ready']}**",
    ]
    if result["draft_cases"]:
        lines.append(f"Draft (unreviewed) cases scored: {', '.join(result['draft_cases'])}")
    if result["pairing_problems"]:
        lines += ["", "Pairing problems:"] + [f"- {p}" for p in result["pairing_problems"]]
    lines += ["", result["note"], ""]

    metrics = [
        ("Cases (run / scheduled)", lambda s: f"{s['cases']} / {s['cases_scheduled']}"),
        ("Runs (errors)", lambda s: f"{s['runs']} ({s['errors']})"),
        ("Passed", lambda s: _pct(s["passed"])),
        ("Action accuracy", lambda s: _pct(s["action_accuracy"])),
        ("Should-ask asked", lambda s: _pct(s["should_ask"])),
        ("False asks", lambda s: _pct(s["false_ask"])),
        ("Clarification targets hit", lambda s: _pct(s["target_coverage"])),
        ("Second turn correct", lambda s: _pct(s["second_turn_accuracy"])),
        ("Recall (macro over cases)", lambda s: _mean(s["recall_macro"])),
        ("Recall (pooled)", lambda s: _pct(s["recall_pooled"])),
        ("Precision (macro, judged)", lambda s: _mean(s["precision_macro"])),
        ("Precision (pooled, judged)", lambda s: _pct(s["precision_pooled"])),
        ("Sample precision (pooled)", lambda s: _pct(s["sample_precision_pooled"])),
        ("Sample recall (pooled)", lambda s: _pct(s["sample_recall_pooled"])),
        ("Sample subsets exactly right", lambda s: _pct(s["subsets_exact"])),
        (
            "Candidates / unjudged / wrong",
            lambda s: f"{s['candidates_total']} / {s['unjudged_total']} / {s['wrong_total']}",
        ),
        ("Fabricated accessions", lambda s: str(s["fabricated_total"])),
        ("Ineligible accessions returned", lambda s: str(s["ineligible_total"])),
        ("Invented but dropped by code", lambda s: str(s["invented_dropped_total"])),
        ("GEO queries / run", lambda s: _mean(s["queries_per_run"], ".1f")),
        ("Web searches / run", lambda s: _mean(s["web_search_requests_per_run"], ".1f")),
        ("Web fetches / run", lambda s: _mean(s["web_fetch_requests_per_run"], ".1f")),
        ("Input tokens / run", lambda s: _mean(s["input_tokens_per_run"], ".0f")),
        ("Output tokens / run", lambda s: _mean(s["output_tokens_per_run"], ".0f")),
        ("Seconds / run", lambda s: _mean(s["elapsed_seconds_per_run"], ".0f")),
    ]
    lines += [
        "| Metric | " + " | ".join(systems) + " |",
        "| --- | " + " | ".join("---" for _ in systems) + " |",
    ]
    for label, fn in metrics:
        lines.append(
            f"| {label} | " + " | ".join(fn(result["summaries"][s]) for s in systems) + " |"
        )

    lines += ["", "## Why positives were missed", ""]
    kinds = ["never_returned", "rejected", "ignored", "not_named"]
    lines += [
        "| System | " + " | ".join(kinds) + " |",
        "| --- | " + " | ".join("---" for _ in kinds) + " |",
    ]
    for s in systems:
        m = result["summaries"][s]["misses"]
        lines.append(f"| {s} | " + " | ".join(str(m.get(k, 0)) for k in kinds) + " |")
    lines += [
        "",
        "never_returned: no GEO query returned it (a search problem). rejected / ignored: GEO "
        "returned it and the agent set it aside or left it out (a judgment problem). not_named: "
        "the baseline has no search trace; it simply did not name it.",
        "",
        "## Questions asked",
        "",
        "Each system's clarifying questions on its first turn, verbatim. Asking is scored yes or "
        "no against the expected action; whether a question was worth asking is for the reader.",
        "",
    ]
    asked = sorted(
        (r for r in result["rows"] if r.get("questions")),
        key=lambda r: (r["case_id"], r["system"], r["repeat"]),
    )
    for r in asked:
        note = "" if r["expected_action"] == "ask" else f" (expected {r['expected_action']})"
        lines.append(f"- **{r['case_id']}** · {r['system']} r{r['repeat']}{note}")
        lines += [f"  - {q}" for q in r["questions"]]
    if not asked:
        lines.append("No system asked a question.")
    lines += [
        "",
        "## Every run",
        "",
        "| Case | System | Rep | Action (expected → got) | 2nd turn | Recall | Precision | "
        "Samples (P / R / exact) | Unjudged | Fabricated | Misses | Error |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in sorted(result["rows"], key=lambda r: (r["case_id"], r["system"], r["repeat"])):
        second = (
            ""
            if r["second_turn_correct"] is None
            else ("ok" if r["second_turn_correct"] else "wrong")
        )
        misses = ", ".join(f"{g} ({k})" for g, k in r["misses"].items()) or "—"
        lines.append(
            f"| {r['case_id']} | {r['system']} | {r['repeat']} | "
            f"{r['expected_action']} → {r['first_action']}{'' if r['action_correct'] else ' ✗'} | "
            f"{second} | {_pct(r['recall'])} | {_pct(r['precision'])} | "
            f"{_pct(r['sample_precision'])} / {_pct(r['sample_recall'])} / "
            f"{_pct(r['subsets_exact'])} | "
            f"{', '.join(r['unjudged']) or '—'} | {', '.join(r['fabricated']) or '—'} | "
            f"{misses} | {r['error'] or ''} |"
        )
    return "\n".join(lines) + "\n"
