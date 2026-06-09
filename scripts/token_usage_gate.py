#!/usr/bin/env python3
"""Claude Code PreToolUse hook for token usage tracking and gating."""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass


TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def coerce_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def token_snapshot_from_usage(usage: dict[str, Any], *, line: int | None = None, message_id: str | None = None) -> dict[str, Any]:
    snapshot = {field: coerce_int(usage.get(field, 0)) for field in TOKEN_FIELDS}
    snapshot["input_side_tokens"] = (
        snapshot["input_tokens"]
        + snapshot["cache_creation_input_tokens"]
        + snapshot["cache_read_input_tokens"]
    )
    snapshot["all_observed_tokens"] = sum(snapshot[field] for field in TOKEN_FIELDS)
    if line is not None:
        snapshot["line"] = line
    if message_id:
        snapshot["message_id"] = message_id
    return snapshot


def read_last_usage(transcript_path: str) -> dict[str, Any]:
    last_usage: dict[str, Any] = {}
    last_line: int | None = None
    last_message_id: str | None = None
    try:
        with open(transcript_path, "r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                try:
                    event = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue
                message = event.get("message") or {}
                usage = message.get("usage")
                if isinstance(usage, dict):
                    last_usage = usage
                    last_line = line_number
                    last_message_id = message.get("id") if isinstance(message.get("id"), str) else None
    except FileNotFoundError:
        pass
    if not last_usage:
        return {"all_observed_tokens": 0, "input_side_tokens": 0}
    return token_snapshot_from_usage(last_usage, line=last_line, message_id=last_message_id)


def project_dir_from_payload(payload: dict[str, Any]) -> Path:
    env_project = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_project:
        return Path(env_project).expanduser()
    cwd = payload.get("cwd") or os.getcwd()
    return Path(str(cwd)).expanduser()


def usage_path_for_project(project_dir: Path) -> Path:
    claude_dir = project_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    return claude_dir / "usage.json"


def load_usage(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "created_at": utc_now(),
            "unblock_code": f"{random.randint(0, 999999):06d}",
            "handoff_allowance_remaining": 0,
        }


def save_usage(path: Path, usage: dict[str, Any]) -> None:
    usage["updated_at"] = utc_now()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(usage, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def emit_allow(additional_context: str | None = None, system_message: str | None = None) -> None:
    if additional_context or system_message:
        output: dict[str, Any] = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }
        if additional_context:
            output["hookSpecificOutput"]["additionalContext"] = additional_context
        if system_message:
            output["systemMessage"] = system_message
        print(json.dumps(output))
    raise SystemExit(0)


def emit_deny(reason: str, system_message: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
            "additionalContext": reason,
        },
        "systemMessage": system_message,
    }))
    raise SystemExit(0)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Block Claude Code tool calls after a token threshold.")
    parser.add_argument("--threshold", type=int, default=900000, help="Maximum last_usage.all_observed_tokens before blocking.")
    parser.add_argument("--handoff-allowance", type=int, default=20, help="Tool calls granted after a valid unblock code.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    payload = json.load(sys.stdin)

    project_dir = project_dir_from_payload(payload)
    usage_path = usage_path_for_project(project_dir)
    usage = load_usage(usage_path)

    transcript_path = payload.get("transcript_path", "")
    last_usage = read_last_usage(str(transcript_path)) if transcript_path else {"all_observed_tokens": 0, "input_side_tokens": 0}

    usage.update({
        "session_id": payload.get("session_id"),
        "cwd": payload.get("cwd"),
        "transcript_path": transcript_path,
        "threshold": args.threshold,
        "last_usage": last_usage,
        "last_tool_name": payload.get("tool_name"),
        "last_checked_at": utc_now(),
    })

    tokens = coerce_int(last_usage.get("all_observed_tokens", 0))
    over_threshold = tokens >= args.threshold

    if over_threshold and coerce_int(usage.get("handoff_allowance_remaining", 0)) > 0:
        usage["handoff_allowance_remaining"] = coerce_int(usage.get("handoff_allowance_remaining", 0)) - 1
        save_usage(usage_path, usage)
        emit_allow(
            additional_context=(
                "Context threshold exceeded, but a user-authorized handoff allowance is active. "
                f"{usage['handoff_allowance_remaining']} tool calls remain. Use them only to finish the requested handoff/wrap-up."
            )
        )

    save_usage(usage_path, usage)

    if over_threshold:
        code = usage.get("unblock_code", "000000")
        reason = (
            f"Agent blocked - hit early context threshold. "
            f"Current last_usage.all_observed_tokens={tokens}; threshold={args.threshold}. "
            f"To permit a short handoff, ask the user to type: unblock {code} <handoff instructions>"
        )
        emit_deny(reason, "Agent blocked - hit early context threshold")

    emit_allow()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
