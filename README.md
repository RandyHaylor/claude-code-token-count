(AI agents should read `SKILL.md`; this `README.md` is about installation and is for users.)

# Claude Code Token Count

Report Claude Code token usage from local session JSONL files and optionally install a project-local hook that blocks tool calls after an early context threshold.

The value Claude Code displays for context usage has matched this script's `last_usage.all_observed_tokens` in real-session checks.

## Install

Clone the repo somewhere stable:

```bash
git clone https://github.com/randyhaylor/claude-code-token-count.git
cd claude-code-token-count
```

The scripts use only the Python standard library. Use `python3` on macOS/Linux or `py -3` on Windows.

## Count A Session

From a direct transcript path:

```bash
python3 scripts/get_token_count.py ~/.claude/projects/<encoded-project>/<session-id>.jsonl
```

From a project cwd plus session id:

```bash
python3 scripts/get_token_count.py --cwd /path/to/project --session-id <session-id>
```

Compact JSON:

```bash
python3 scripts/get_token_count.py --cwd /path/to/project --session-id <session-id> --json
```

## Install The Token Gate Hook

In your project, create or edit `.claude/settings.local.json`. If the file already exists, merge these hooks into it and preserve any existing settings or hook commands:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /absolute/path/to/claude-code-token-count/scripts/token_usage_gate.py --threshold 900000"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /absolute/path/to/claude-code-token-count/scripts/unblock_via_prompt.py"
          }
        ]
      }
    ]
  }
}
```

Change `--threshold 900000` per project if you want a different early-context cutoff.

The gate writes and updates:

```text
<project>/.claude/usage.json
```

When the session reaches the threshold, the hook blocks tool calls and shows:

```text
Halted at context threshold (<used>/<limit>). To unblock and provide hand off instruction to the agent for this session, type "unblock <code> <hand off instructions>".
```

By default the gate uses hard-stop behavior: it returns top-level `continue:false`, ends the whole turn, and the agent prints nothing. To use the older behavior that only denies the current tool call and lets the agent explain, add `--behavior deny` to the hook command.

To allow a short handoff window, submit:

```text
unblock 123456 write a handoff document
```

The block message includes a suggested prompt:

```text
unblock 123456 write a detailed handoff.md doc to allow another agent to continue this work
```

Use the six-digit code from `.claude/usage.json`.

## Notes

Claude Code hook payloads include `transcript_path`, which points at the current session JSONL. The scripts read that file for `message.usage` token breadcrumbs. Treat the transcript JSONL as read-only; editing it is not a reliable way to change a Claude Code session.

## License

MIT
