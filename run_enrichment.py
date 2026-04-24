"""CLI entrypoint for the enrichment agent. Populates the ``contact`` table.

Usage:
    python run_enrichment.py                # enrich every company missing a contact
    python run_enrichment.py --model gpt-4o # override model
    python run_enrichment.py --dry-run      # call tools but do not write to SQLite
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.agent.enrichment_tools import (
    ENRICHMENT_HANDLERS,
    ENRICHMENT_TOOLS,
    load_enrichment_system_prompt,
)
from src.agent.orchestrator import run_agent
from src.db import get_connection

DEFAULT_MODEL = "gpt-4o"


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-turns", type=int, default=40)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Call tools but do not write contact rows.",
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
            tools=ENRICHMENT_TOOLS,
            handlers=ENRICHMENT_HANDLERS,
            system_prompt=load_enrichment_system_prompt(),
            tag="enrichment",
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
