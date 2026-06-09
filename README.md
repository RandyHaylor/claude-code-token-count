(AI agents should read `SKILL.md`; this `README.md` is about installation and is for users.)

# Claude Code Token Count

Report Claude Code token usage from local session JSONL files and optionally install a project-local hook that blocks tool calls after an early context threshold.

The value Claude Code displays for context usage has matched this script's `last_usage.all_observed_tokens` in real-session checks.

Suggested usage: install this skill once, then keep working normally. If you notice a Claude Code session's context getting high, for example above 600k tokens, ask the agent to set up the token counting guard for that project.

## Install

Clone directly into the Claude Code user-level skills folder:

```bash
# Linux
git clone https://github.com/randyhaylor/claude-code-token-count.git ~/.claude/skills/claude-code-token-count

# macOS
git clone https://github.com/randyhaylor/claude-code-token-count.git ~/.claude/skills/claude-code-token-count
```

```cmd
REM Windows (Command Prompt)
git clone https://github.com/randyhaylor/claude-code-token-count.git "%USERPROFILE%\.claude\skills\claude-code-token-count"
```

```powershell
# Windows (PowerShell)
git clone https://github.com/randyhaylor/claude-code-token-count.git "$env:USERPROFILE\.claude\skills\claude-code-token-count"
```

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

Do not grant Claude broad or permanent permission to edit the project `.claude/` folder. The hook settings and `usage.json` live there; unrestricted access could let the agent alter or remove the gate and circumvent the block.

When the session reaches the threshold, the hook blocks tool calls and shows:

```text
HALTED AT CONTEXT THRESHOLD (<used>/<limit>): The agent must wait and not say or do anything without further user direction

TO UNBLOCK AND PROVIDE HAND OFF INSTRUCTION TO THE AGENT FOR THIS SESSION, type "unblock <code> <hand off instructions>".

Suggested prompt: "unblock <code> write a detailed handoff.md doc to allow another agent to continue this work"
```

By default the gate uses hard-stop behavior: it returns top-level `continue:false` and `stopReason`; it ends the whole turn, and the agent prints nothing. To use the older behavior that only denies the current tool call and lets the agent explain, add `--behavior deny` to the hook command.

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
