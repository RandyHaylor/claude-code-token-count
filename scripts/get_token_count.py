#!/usr/bin/env python3
"""Summarize token usage from Claude Code session JSONL files.

The script intentionally depends only on the Python standard library so it runs
on Linux, macOS, and Windows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


COMMON_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)
DERIVED_TOKEN_FIELDS = {
    "input_side_tokens",
    "all_observed_tokens",
}


def encode_claude_project_dir(cwd: Path) -> str:
    """Approximate Claude Code's ~/.claude/projects directory name for a cwd."""
    text = str(cwd.expanduser().resolve())
    text = text.replace("\\", "/")
    text = text.lstrip("/")
    text = text.replace(":", "")
    return "-" + text.replace("/", "-")


def default_claude_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def resolve_jsonl_path(args: argparse.Namespace) -> Path:
    if args.jsonl_path:
        return Path(args.jsonl_path).expanduser()

    projects_dir = Path(args.projects_dir).expanduser() if args.projects_dir else default_claude_projects_dir()

    if args.latest_for_cwd:
        cwd = Path(args.latest_for_cwd)
        project_dir = projects_dir / encode_claude_project_dir(cwd)
        jsonl_paths = sorted(
            project_dir.glob("*.jsonl"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not jsonl_paths:
            raise FileNotFoundError(f"No JSONL files found in {project_dir}")
        return jsonl_paths[0]

    if args.cwd and args.session_id:
        cwd = Path(args.cwd)
        project_dir = projects_dir / encode_claude_project_dir(cwd)
        candidate = project_dir / f"{args.session_id}.jsonl"
        if candidate.exists():
            return candidate

        fallback_matches = list(projects_dir.glob(f"*/{args.session_id}.jsonl"))
        if len(fallback_matches) == 1:
            return fallback_matches[0]
        if len(fallback_matches) > 1:
            joined = "\n".join(str(path) for path in fallback_matches)
            raise RuntimeError(f"Session id matched multiple JSONL files:\n{joined}")
        return candidate

    raise ValueError("Provide a JSONL path, --latest-for-cwd, or both --cwd and --session-id")


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


def extract_usage_blocks(jsonl_path: Path, *, count_duplicates: bool) -> tuple[list[dict[str, Any]], int]:
    usage_blocks: list[dict[str, Any]] = []
    seen_message_ids: set[str] = set()
    duplicate_blocks = 0
    with jsonl_path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue

            message = event.get("message") or {}
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue

            message_id = message.get("id")
            if isinstance(message_id, str) and message_id:
                if message_id in seen_message_ids:
                    duplicate_blocks += 1
                    if not count_duplicates:
                        continue
                else:
                    seen_message_ids.add(message_id)

            token_fields = {
                key: coerce_int(value)
                for key, value in usage.items()
                if key.endswith("_tokens")
            }
            if not token_fields:
                continue

            block = dict(token_fields)
            block["_line"] = line_number
            block["_type"] = event.get("type")
            block["_message_id"] = message_id
            usage_blocks.append(block)
    return usage_blocks, duplicate_blocks


def sum_token_fields(blocks: list[dict[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for block in blocks:
        for key, value in block.items():
            if key.startswith("_") or not key.endswith("_tokens"):
                continue
            totals[key] = totals.get(key, 0) + coerce_int(value)
    return totals


def with_derived_totals(values: dict[str, int]) -> dict[str, int]:
    result = dict(values)
    result["input_side_tokens"] = (
        result.get("input_tokens", 0)
        + result.get("cache_creation_input_tokens", 0)
        + result.get("cache_read_input_tokens", 0)
    )
    result["all_observed_tokens"] = sum(
        value
        for key, value in result.items()
        if key.endswith("_tokens") and key not in DERIVED_TOKEN_FIELDS
    )
    return result


def ordered_token_items(values: dict[str, int]) -> list[tuple[str, int]]:
    seen = set()
    ordered: list[tuple[str, int]] = []
    for key in COMMON_TOKEN_FIELDS:
        if key in values:
            ordered.append((key, values[key]))
            seen.add(key)
    for key in sorted(values):
        if key.endswith("_tokens") and key not in seen and key not in DERIVED_TOKEN_FIELDS:
            ordered.append((key, values[key]))
            seen.add(key)
    for key in ("input_side_tokens", "all_observed_tokens"):
        if key in values:
            ordered.append((key, values[key]))
    return ordered


def print_human_report(
    path: Path,
    blocks: list[dict[str, Any]],
    by_message: bool,
    duplicate_blocks: int,
    counted_duplicates: bool,
) -> None:
    aggregate = with_derived_totals(sum_token_fields(blocks))
    last_usage = with_derived_totals({
        key: coerce_int(value)
        for key, value in (blocks[-1] if blocks else {}).items()
        if key.endswith("_tokens")
    })

    print(f"session_jsonl: {path}")
    print(f"usage_blocks: {len(blocks)}")
    print(f"duplicate_usage_blocks_skipped: {0 if counted_duplicates else duplicate_blocks}")
    if counted_duplicates:
        print(f"duplicate_usage_blocks_counted: {duplicate_blocks}")

    print("\naggregate:")
    if aggregate:
        for key, value in ordered_token_items(aggregate):
            print(f"  {key}: {value}")
    else:
        print("  none")

    print("\nlast_usage:")
    if last_usage:
        print(f"  line: {blocks[-1]['_line']}")
        for key, value in ordered_token_items(last_usage):
            print(f"  {key}: {value}")
    else:
        print("  none")

    if by_message:
        print("\nby_message:")
        for index, block in enumerate(blocks, start=1):
            line = block.get("_line")
            token_summary = ", ".join(
                f"{key}={value}"
                for key, value in ordered_token_items(with_derived_totals({
                    k: coerce_int(v) for k, v in block.items() if k.endswith("_tokens")
                }))
            )
            print(f"  {index}. line={line}: {token_summary}")


def build_json_report(
    path: Path,
    blocks: list[dict[str, Any]],
    duplicate_blocks: int,
    counted_duplicates: bool,
    include_by_message: bool,
) -> dict[str, Any]:
    aggregate = with_derived_totals(sum_token_fields(blocks))
    last_block = blocks[-1] if blocks else {}
    last_usage = with_derived_totals({
        key: coerce_int(value)
        for key, value in last_block.items()
        if key.endswith("_tokens")
    })
    report: dict[str, Any] = {
        "session_jsonl": str(path),
        "usage_blocks": len(blocks),
        "duplicate_usage_blocks_skipped": 0 if counted_duplicates else duplicate_blocks,
        "duplicate_usage_blocks_counted": duplicate_blocks if counted_duplicates else 0,
        "aggregate": aggregate,
        "last_usage": {
            "line": last_block.get("_line"),
            "message_id": last_block.get("_message_id"),
            **last_usage,
        } if last_block else {},
    }
    if include_by_message:
        report["by_message"] = blocks
    return report


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize Claude Code token usage from session JSONL message.usage objects."
    )
    parser.add_argument("jsonl_path", nargs="?", help="Path to a Claude Code session .jsonl file.")
    parser.add_argument("--cwd", help="Project cwd used by Claude Code for the session.")
    parser.add_argument("--session-id", help="Claude Code session id / JSONL basename without .jsonl.")
    parser.add_argument("--latest-for-cwd", help="Use the newest JSONL under the Claude project log dir for this cwd.")
    parser.add_argument("--projects-dir", help="Override the Claude projects directory. Defaults to ~/.claude/projects.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a human-readable report.")
    parser.add_argument("--by-message", action="store_true", help="Include one row per usage-bearing JSONL event.")
    parser.add_argument(
        "--count-duplicates",
        action="store_true",
        help="Count repeated usage blocks with the same message.id instead of deduplicating them.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    try:
        path = resolve_jsonl_path(args)
        if not path.is_file():
            raise FileNotFoundError(f"JSONL file not found: {path}")
        blocks, duplicate_blocks = extract_usage_blocks(path, count_duplicates=args.count_duplicates)
        if args.json:
            print(json.dumps(
                build_json_report(
                    path,
                    blocks,
                    duplicate_blocks,
                    args.count_duplicates,
                    args.by_message,
                ),
                indent=2,
                sort_keys=True,
            ))
        else:
            print_human_report(path, blocks, args.by_message, duplicate_blocks, args.count_duplicates)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
