"""The project folder is the product; ambiguities remain visible in questions.md."""

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from cell_ledger.geo.cache import CachedClient
from cell_ledger.interpretation import Interpreter
from cell_ledger.pipeline import RunRequest, run_pipeline


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("topic")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--organism", default="human")
    parser.add_argument("--max-datasets", type=int, default=3)
    parser.add_argument("--min-per-group", type=int, default=3)
    parser.add_argument("--since", type=int)
    parser.add_argument("--case", help="Exact case condition/treatment value in source metadata")
    parser.add_argument(
        "--control", help="Exact control condition/treatment value in source metadata"
    )
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--model", default=os.getenv("CELL_LEDGER_MODEL"))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--ask", action="store_true", help="Pause for unresolved group labels")
    mode.add_argument("--auto", action="store_true", help="Record ambiguities and keep going")
    parser.add_argument("--cache", type=Path, default=Path("data/geo/cache"))
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error("Output folder already exists; choose a new folder to preserve previous runs")
    request = RunRequest(
        **{
            key: value
            for key, value in vars(args).items()
            if key not in {"out", "cache", "model", "ask", "auto"}
        }
    )
    client = CachedClient(
        args.cache,
        offline=args.offline,
        api_key=os.getenv("CELL_LEDGER_NCBI_API_KEY", os.getenv("NCBI_API_KEY")),
    )
    interpreter = None
    if args.model:
        key = os.getenv("CELL_LEDGER_ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_API_KEY", ""))
        if not key and not args.offline:
            parser.error(
                "Set CELL_LEDGER_ANTHROPIC_API_KEY (or ANTHROPIC_API_KEY) for --model, "
                "or omit --model for exact-label mode"
            )
        interpreter = Interpreter(
            args.model, key, args.cache / "interpretations", offline=args.offline
        )

    async def ask(gse: str, options: list[str]) -> tuple[str, str] | None:
        print(f"{gse}: choose case and control from these exact source labels: {options}")
        case = await asyncio.to_thread(input, "Case (blank to leave unresolved): ")
        if not case:
            return None
        control = await asyncio.to_thread(input, "Control: ")
        return case, control

    result = asyncio.run(
        run_pipeline(
            request,
            args.out,
            client,
            emit=lambda stage, message: print(f"[{stage}] {message}"),
            interpreter=interpreter,
            ask=ask if args.ask else None,
        )
    )
    print(f"{result['status']}: {args.out.resolve()}")
    if result["status"] in {"error", "unsupported"}:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
