#!/usr/bin/env python3
"""Claude Code UserPromptSubmit hook for handoff unblocking."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

UNBLOCK_RE = re.compile(r"^\s*unblock\s+(\d{6})\b(.*)$", re.IGNORECASE | re.DOTALL)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def project_dir_from_payload(payload: dict[str, Any]) -> Path:
    env_project = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_project:
        return Path(env_project).expanduser()
    cwd = payload.get("cwd") or os.getcwd()
    return Path(str(cwd)).expanduser()


def usage_path_for_project(project_dir: Path) -> Path:
    return project_dir / ".claude" / "usage.json"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grant handoff allowance after user submits unblock <code>.")
    parser.add_argument("--allowance", type=int, default=20, help="Tool calls to allow for handoff after a valid unblock code.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    payload = json.load(sys.stdin)
    prompt = payload.get("prompt", "")

    match = UNBLOCK_RE.match(prompt)
    if not match:
        return 0

    code = match.group(1)
    instructions = match.group(2).strip()
    usage_path = usage_path_for_project(project_dir_from_payload(payload))

    try:
        usage = json.loads(usage_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return 0

    if code != str(usage.get("unblock_code", "")):
        return 0

    usage["handoff_unlock_used"] = True
    usage["handoff_allowance_remaining"] = int(usage.get("handoff_allowance_remaining", 0)) + args.allowance
    usage["handoff_unlocked_at"] = utc_now()
    usage_path.write_text(json.dumps(usage, indent=2, sort_keys=True), encoding="utf-8")

    note = (
        "Session unblocked for wrap-up. A short tool-call allowance has been granted. "
        "Use it only to complete the user's handoff/wrap-up request, then stop.\n\n"
        f"{instructions or 'Write a concise handoff or summary document for this session.'}"
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": note,
        },
        "systemMessage": "Agent unblocked for handoff allowance",
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
