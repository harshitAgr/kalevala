# kalevala

Daily journal of Claude Code work. A `SessionEnd` hook summarizes each session via `claude --print`, scrubs secrets, and commits to a private journal repo.

## What it does

- One markdown file per day under `entries/YYYY/MM/YYYY-MM-DD.md`; a session is filed under the days its turns were written (a session closed the next morning still lands on yesterday), split per day if it spans several
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
# Make `kalevala` available on PATH for the /kalevala slash command
ln -sf ~/projects/kalevala/.venv/bin/kalevala ~/.local/bin/kalevala
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
# optional: dotenv-style files whose every value is scrubbed by exact match
secret_env_files = ["~/.config/mytool/env"]
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
kalevala sweep             # journal recent sessions that ended without running the hook
kalevala status            # pending count, state health, error count
kalevala check            # compare the 7 days before today with the transcripts on disk (--days N)
kalevala check 2026-04-17 # one day; exits 1 if a session is missing or misfiled (sessions still running are listed as open and don't fail it)
kalevala rebuild 2026-04-17  # regenerate a day from its transcripts (keeps manual notes)
```

`check` and `rebuild` read `~/.claude/projects` (or `$CLAUDE_CONFIG_DIR/projects`), so they only
reach back as far as Claude Code keeps transcripts (`cleanupPeriodDays`, 30 by default). `rebuild`
refuses a day whose entry lists a session that no longer has a transcript, and refuses to drop a
misfiled session whose own days are not part of the rebuild (rebuild them together, or pass
`--allow-drop <id>` when its work is already filed elsewhere). It also refuses when a summary reaches
the scrub threshold (`--allow-drop <id>` leaves that session out). Finished summaries are cached, so
a rebuild that fails part-way resumes when run again.

Days and times use the machine's local zone. To use another, set an IANA name in `config.toml`:

```toml
timezone = "Europe/Helsinki"
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
- **Exact-value scrubbing** catches secrets that have no recognisable shape (a 40-hex API token, a database password). The scrubber also redacts, by exact match, the values of environment variables named like `*_TOKEN`, `*_KEY`, `*SECRET`, `*PASSWORD`; the `env` and `headers` of every MCP server in `~/.claude.json` (or `$CLAUDE_CONFIG_DIR/.claude.json`); and every value in the files listed in `secret_env_files`. Values under 16 characters (8 for `secret_env_files`), plain URLs, existing file paths and `${VAR}` references are skipped so ordinary text is not eaten. If a source cannot be read, the session is not journaled (its cursor stays put, and the sweep picks it up once fixed) rather than scrubbed with fewer secrets. It only knows secrets that exist on this machine now: an altered or truncated copy of a secret, or one that has since been rotated away, is not caught
- **Path normalizer** rewrites absolute paths (`$HOME` → `~/`, `$CLAUDE_PROJECT_DIR` → `<project>/`) so machine layout doesn't leak
- **Prompt-injection mitigation** — transcript content is delimited and labeled "data only" in both system and user prompts
- **File lock** (fcntl) serializes concurrent hook runs; lock timeouts queue rather than drop
- **Retry queue** with exponential backoff for 429 and network failures
- **Sweep** for sessions that end without `SessionEnd`: the background-agent daemon retires idle agents without firing it, and a killed terminal skips it. Each hook run also journals up to 3 transcripts written in the last 7 days that have turns past their cursor and whose process is gone; `kalevala sweep` does all of them at once
- **Scrub threshold** safety net — if >20 redactions fire for one session, the write is aborted and queued for manual review

## Requirements

- Python 3.11+
- `claude` CLI on PATH (Claude Code)
- Local POSIX filesystem (fcntl locks are unreliable on NFS)

## Troubleshooting

- `kalevala status` — pending queue, state file health, recent error count
- `kalevala drain` — manually retry queued pushes
- `kalevala sweep` — journal sessions the hook never saw (retired background agents, killed terminals)
- `kalevala check` — find days whose entry disagrees with the transcripts; `kalevala rebuild <date>` fixes one
- `kalevala hook --verify-scrub --transcript-path <path>` — dry-run the scrubber against any transcript
- Errors go to `<log_repo>/.kalevala/errors.log` and `~/.kalevala/hook.err`

## License

Personal use.
