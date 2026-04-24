"""CLI entrypoint for the ingestion agent.

Usage:
    python run_agent.py                   # run once against the live DB
    python run_agent.py --dry-run         # no persistence; just classify + summarize
    python run_agent.py --model gpt-4o    # override model
    python run_agent.py --max-turns 50    # raise the turn ceiling
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.agent.orchestrator import DEFAULT_MODEL, run_agent
from src.db import get_connection


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-turns", type=int, default=30)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write to SQLite. Classifier still runs.",
    )
    parser.add_argument("--db-path", type=Path, default=None)
    args = parser.parse_args()

    conn = None if args.dry_run else get_connection(args.db_path)
    try:
        result = run_agent(
            conn=conn,
            model=args.model,
            max_turns=args.max_turns,
            persist=not args.dry_run,
        )
    finally:
        if conn is not None:
            conn.close()

    print(f"turns={result.turns} tool_calls={result.tool_calls} finished={result.finished}")
    print(f"log: {result.log_path}")
    if result.summary:
        import json

        print("summary:")
        print(json.dumps(result.summary, indent=2, default=str))
    return 0 if result.finished else 1


if __name__ == "__main__":
    sys.exit(main())
