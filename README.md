# kalevala

Daily journal of Claude Code work, auto-generated via a SessionEnd hook.

## Install

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
```

Then wire the SessionEnd hook in `~/.claude/settings.json` (see Task 16 of the implementation plan).

## Usage

```
kalevala hook --session-id <id> --transcript-path <path>  # called by the hook
kalevala note "remember to X"
kalevala todo "fix Y next week"
kalevala show [YYYY-MM-DD]
kalevala last
kalevala search <query>
kalevala resume <query>
kalevala drain
kalevala status
```

## Requirements

- Python 3.11+
- Local POSIX filesystem (fcntl locks unreliable on NFS)
- `ANTHROPIC_API_KEY` in environment
