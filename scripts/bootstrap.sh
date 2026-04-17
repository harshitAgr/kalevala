#!/usr/bin/env bash
# Idempotent setup for using kalevala on a new machine with the same user.
# - Clones kalevala + kalevala-log (skips if already present)
# - Creates venv, installs the tool
# - Writes ~/.config/kalevala/config.toml (skips if already present)
# - Installs the /kalevala skill
# - Merges a SessionEnd hook into ~/.claude/settings.json via jq
#
# Usage:
#   ./scripts/bootstrap.sh <your-github-username>
#
# Assumes: git, python >= 3.11, jq, and the `claude` CLI are installed.

set -euo pipefail

GH_USER="${1:-}"
if [[ -z "$GH_USER" ]]; then
    echo "usage: $0 <github-username>" >&2
    echo "  example: $0 harshitAgr" >&2
    exit 1
fi

PROJECTS_DIR="$HOME/projects"
TOOL_DIR="$PROJECTS_DIR/kalevala"
LOG_DIR="$PROJECTS_DIR/kalevala-log"
CONFIG_FILE="$HOME/.config/kalevala/config.toml"
SETTINGS_FILE="$HOME/.claude/settings.json"
SKILL_DIR="$HOME/.claude/skills/kalevala"

mkdir -p "$PROJECTS_DIR"

# 1. Clone repos if missing
if [[ ! -d "$TOOL_DIR/.git" ]]; then
    echo "[1/5] cloning kalevala tool..."
    git clone "git@github.com:${GH_USER}/kalevala.git" "$TOOL_DIR"
else
    echo "[1/5] kalevala tool already cloned — pulling"
    git -C "$TOOL_DIR" pull --ff-only
fi

if [[ ! -d "$LOG_DIR/.git" ]]; then
    echo "[1/5] cloning kalevala-log journal..."
    git clone "git@github.com:${GH_USER}/kalevala-log.git" "$LOG_DIR"
else
    echo "[1/5] kalevala-log already cloned — pulling"
    git -C "$LOG_DIR" pull --ff-only
fi

# 2. Install tool in venv
if [[ ! -x "$TOOL_DIR/.venv/bin/kalevala" ]]; then
    echo "[2/5] creating venv and installing kalevala..."
    python3 -m venv "$TOOL_DIR/.venv"
    "$TOOL_DIR/.venv/bin/pip" install -q -e "$TOOL_DIR"
else
    echo "[2/5] kalevala already installed in venv"
fi

# 3. Config
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "[3/5] writing $CONFIG_FILE"
    mkdir -p "$(dirname "$CONFIG_FILE")"
    cat > "$CONFIG_FILE" <<EOF
log_repo_path = "$LOG_DIR"
model = "claude-sonnet-4-6"
auto_push = true
git_remote = "origin"
git_branch = "main"
scrub_threshold = 20
lock_wait_seconds = 30
EOF
    chmod 600 "$CONFIG_FILE"
else
    echo "[3/5] config already exists at $CONFIG_FILE (unchanged)"
fi

# 4. Skill
mkdir -p "$SKILL_DIR"
if ! cmp -s "$TOOL_DIR/skills/kalevala/SKILL.md" "$SKILL_DIR/SKILL.md"; then
    echo "[4/5] installing /kalevala skill"
    cp "$TOOL_DIR/skills/kalevala/SKILL.md" "$SKILL_DIR/SKILL.md"
else
    echo "[4/5] /kalevala skill already up to date"
fi

# 5. SessionEnd hook — merge into settings.json without clobbering existing hooks
mkdir -p "$HOME/.kalevala"
HOOK_CMD="$TOOL_DIR/.venv/bin/kalevala hook 2>>\$HOME/.kalevala/hook.err || true"

if [[ ! -f "$SETTINGS_FILE" ]]; then
    echo "[5/5] creating $SETTINGS_FILE with SessionEnd hook"
    mkdir -p "$(dirname "$SETTINGS_FILE")"
    cat > "$SETTINGS_FILE" <<EOF
{
  "hooks": {
    "SessionEnd": [
      { "hooks": [{ "type": "command", "command": "$HOOK_CMD" }] }
    ]
  }
}
EOF
elif jq -e --arg cmd "$HOOK_CMD" \
    '.hooks.SessionEnd // [] | map(.hooks // []) | flatten | map(.command) | index($cmd)' \
    "$SETTINGS_FILE" > /dev/null 2>&1; then
    echo "[5/5] SessionEnd hook already installed (no change)"
else
    echo "[5/5] merging SessionEnd hook into $SETTINGS_FILE"
    TMP=$(mktemp)
    jq --arg cmd "$HOOK_CMD" '
        .hooks = (.hooks // {})
        | .hooks.SessionEnd = (.hooks.SessionEnd // [])
        | .hooks.SessionEnd += [{"hooks": [{"type": "command", "command": $cmd}]}]
    ' "$SETTINGS_FILE" > "$TMP" && mv "$TMP" "$SETTINGS_FILE"
fi

echo ""
echo "Done. Next:"
echo "  - Restart Claude Code (or open /hooks once) so it picks up the new SessionEnd hook."
echo "  - End any Claude Code session and check: ls $LOG_DIR/entries/"
echo "  - Run $TOOL_DIR/.venv/bin/kalevala status to verify health."
