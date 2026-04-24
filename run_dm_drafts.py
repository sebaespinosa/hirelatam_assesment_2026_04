"""CLI entrypoint for the DM-draft agent. Populates ``dm_draft`` for under-performing launches.

Usage:
    python run_dm_drafts.py                # draft DMs for every qualifying launch
    python run_dm_drafts.py --model gpt-4o # override model
    python run_dm_drafts.py --dry-run      # generate drafts but do not write to SQLite
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.agent.dm_tools import DM_HANDLERS, DM_TOOLS, load_dm_system_prompt
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
    parser.add_argument("--max-turns", type=int, default=15)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Draft DMs but do not write dm_draft rows.",
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
            tools=DM_TOOLS,
            handlers=DM_HANDLERS,
            system_prompt=load_dm_system_prompt(),
            tag="dm_drafts",
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
