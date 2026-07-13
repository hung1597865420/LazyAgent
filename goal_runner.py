"""CLI entry point for the Agent Harness direct goal runner."""
from __future__ import annotations

import argparse
import asyncio
import json

from tools.runner import goal_runner


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one prompt through Agent Harness goal automation.")
    parser.add_argument("prompt", nargs="+", help="Prompt/goal to run")
    parser.add_argument("--mode", choices=["safe", "max"], default="max")
    parser.add_argument("--max-iterations", type=int, default=8)
    parser.add_argument("--agent-command", default=None, help='Command template; use "{prompt}" placeholder or prompt is appended')
    parser.add_argument("--agent-timeout", type=float, default=900.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-prod-gate", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(goal_runner(
        " ".join(args.prompt),
        max_iterations=args.max_iterations,
        mode=args.mode,
        agent_command=args.agent_command,
        agent_timeout=args.agent_timeout,
        dry_run=args.dry_run,
        final_prod_gate=not args.no_prod_gate,
    ))
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
