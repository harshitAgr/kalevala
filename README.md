# kalevala

Daily journal of Claude Code work. A `SessionEnd` hook summarizes each session via `claude --print`, scrubs secrets, and commits to a private journal repo.

## What it does

- One markdown file per day under `entries/YYYY/MM/YYYY-MM-DD.md`
- Rich content per session: summary, files touched, commits, bugs fixed, decisions, learnings, notes for later, open threads
- Tracks session IDs so you can `claude --resume <id>` straight from the journal
- Auto-commits and pushes to a private GitHub repo (separate from this tool)
- `/kalevala` slash command inside Claude Code for notes, search, and lookup

## Auth — no API key required

This tool shells out to the `claude` CLI with `--no-session-persistence`, so it reuses whatever authentication Claude Code is already configured with (Pro/Max OAuth, Console API key, etc.). You don't need to export `ANTHROPIC_API_KEY`.

## Install

### Quick bootstrap (new machine, same user)

Clones both repos, creates the venv, writes config, installs the skill, and merges the SessionEnd hook in one shot:

```bash
git clone git@github.com:<your-user>/kalevala.git ~/projects/kalevala
~/projects/kalevala/scripts/bootstrap.sh <your-user>
```

The script is idempotent — safe to re-run to update.

### Manual install

```bash
pip install -e ~/projects/kalevala
```

Create `~/.config/kalevala/config.toml`:

```toml
log_repo_path = "~/projects/kalevala-log"
model = "claude-sonnet-4-6"
auto_push = true
git_remote = "origin"
git_branch = "main"
scrub_threshold = 20
lock_wait_seconds = 30
```

Make sure `~/projects/kalevala-log/` is a git repo with a remote pointing at your private journal repo.

## Wire the hook

Add to `~/.claude/settings.json` (merge with any existing hooks):

```json
{
  "hooks": {
    "SessionEnd": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "/home/YOU/projects/kalevala/.venv/bin/kalevala hook 2>>$HOME/.kalevala/hook.err || true"
          }
        ]
      }
    ]
  }
}
```

The hook reads its payload (session_id, transcript_path) as JSON from stdin — no args needed. Claude Code may need a restart or a `/hooks` open to pick up the new config.

## Install the slash command

```bash
mkdir -p ~/.claude/skills/kalevala
cp ~/projects/kalevala/skills/kalevala/SKILL.md ~/.claude/skills/kalevala/SKILL.md
```

## Usage

```
kalevala note "try the new cache layout"
kalevala todo "refactor the auth middleware next week"
kalevala show              # today's entry
kalevala show 2026-04-17   # a specific date
kalevala last              # yesterday's entry
kalevala search <query>    # grep across all entries
kalevala resume <query>    # print `claude --resume <id>` for the matching session
kalevala drain             # manually retry queued commits/pushes
kalevala status            # pending count, state health, error count
```

Or from inside Claude Code:

```
/kalevala note "..."
/kalevala search val-loop
/kalevala resume "auth middleware"
```

## Safety & design highlights

- **Atomic writes** (tempfile + `os.replace`) — the daily markdown file is always valid
- **Secret scrubber** (RE2 regex, no ReDoS) redacts API keys, tokens, private keys, AWS creds, bearer tokens, JWTs, env-var-style leaks
- **Path normalizer** rewrites absolute paths (`$HOME` → `~/`, `$CLAUDE_PROJECT_DIR` → `<project>/`) so machine layout doesn't leak
- **Prompt-injection mitigation** — transcript content is delimited and labeled "data only" in both system and user prompts
- **File lock** (fcntl) serializes concurrent hook runs; lock timeouts queue rather than drop
- **Retry queue** with exponential backoff for 429 and network failures
- **Scrub threshold** safety net — if >20 redactions fire for one session, the write is aborted and queued for manual review

## Requirements

- Python 3.11+
- `claude` CLI on PATH (Claude Code)
- Local POSIX filesystem (fcntl locks are unreliable on NFS)

## Troubleshooting

- `kalevala status` — pending queue, state file health, recent error count
- `kalevala drain` — manually retry queued pushes
- `kalevala hook --verify-scrub --transcript-path <path>` — dry-run the scrubber against any transcript
- Errors go to `<log_repo>/.kalevala/errors.log` and `~/.kalevala/hook.err`

## License

Personal use.
