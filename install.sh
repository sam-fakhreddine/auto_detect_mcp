#!/usr/bin/env bash
set -euo pipefail

HOOK_DEST="$HOME/.claude/hooks/auto_detect_mcp.py"
CONFIG_DIR="$HOME/.config/auto-detect-mcp/configs"
SETTINGS="$HOME/.claude/settings.json"
HOOK_CMD="python3 $HOME/.claude/hooks/auto_detect_mcp.py"

echo "Installing auto-detect-mcp..."

# Must run from repo root
[[ -f "hook.py" ]] || { echo "Error: hook.py not found. Run from the repository root." >&2; exit 1; }
[[ -d "configs" ]] || { echo "Error: configs/ directory not found." >&2; exit 1; }
compgen -G "configs/*.toml" > /dev/null 2>&1 || { echo "Error: no configs/*.toml found." >&2; exit 1; }

# Require python3
command -v python3 >/dev/null 2>&1 || { echo "Error: python3 not found in PATH." >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' \
  || { echo "Error: Python 3.12+ required." >&2; exit 1; }

# Trap for partial install cleanup messaging
trap 'echo "Install failed. Check $SETTINGS.bak.* to restore settings if needed." >&2' ERR

# ── Hook ──────────────────────────────────────────────────────────────────────
mkdir -p "$HOME/.claude/hooks"
cp hook.py "$HOOK_DEST"
chmod +x "$HOOK_DEST"
echo "  ✓ Hook installed to $HOOK_DEST"

# ── Configs ───────────────────────────────────────────────────────────────────
mkdir -p "$CONFIG_DIR"
for f in configs/*.toml; do
  name=$(basename "$f")
  dest="$CONFIG_DIR/$name"
  if [[ "$name" == example-* ]]; then
    if [[ ! -f "$dest" ]]; then
      cp "$f" "$dest"
      echo "  ✓ Example config installed: $dest"
    else
      echo "  - Skipping existing example: $dest"
    fi
  else
    if [[ -f "$dest" ]]; then
      cp "$dest" "$dest.bak"
      echo "  ! Backed up existing config to $dest.bak"
    fi
    cp "$f" "$dest"
    echo "  ✓ Config installed: $dest"
  fi
done

# ── settings.json ─────────────────────────────────────────────────────────────
if [[ ! -f "$SETTINGS" ]]; then
  mkdir -p "$(dirname "$SETTINGS")"
  echo '{"hooks":{"UserPromptSubmit":[]}}' > "$SETTINGS" \
    || { echo "Error: cannot create $SETTINGS" >&2; exit 1; }
fi

# Backup before patching
cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"
echo "  ✓ Settings backed up"

# Patch via python — use env vars to avoid heredoc injection
HOOK_CMD="$HOOK_CMD" SETTINGS_PATH="$SETTINGS" python3 - <<'PYEOF'
import json, os, sys
from pathlib import Path

settings_path = Path(os.environ["SETTINGS_PATH"])
hook_cmd = os.environ["HOOK_CMD"]

try:
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
except json.JSONDecodeError as e:
    print(f"Error: invalid JSON in {settings_path}: {e}", file=sys.stderr)
    sys.exit(1)
except OSError as e:
    print(f"Error: cannot read {settings_path}: {e}", file=sys.stderr)
    sys.exit(1)

settings.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])
ups = settings["hooks"]["UserPromptSubmit"]

# Idempotency: check for exact command match before adding
for entry in ups:
    for hook in entry.get("hooks", []):
        if hook.get("command") == hook_cmd:
            print("  - Hook already registered, skipping")
            sys.exit(0)

target = next((h for h in ups if h.get("matcher") == ""), None)
if target is None:
    target = {"matcher": "", "hooks": []}
    ups.append(target)

target["hooks"].append({"type": "command", "command": hook_cmd})

try:
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
except OSError as e:
    print(f"Error: cannot write {settings_path}: {e}", file=sys.stderr)
    sys.exit(1)

print("  ✓ Hook registered in settings.json")
PYEOF

echo ""
echo "Done. Add your own configs to: $CONFIG_DIR"
echo "On the next Claude Code session in a matching repo, .mcp.json will be auto-written."
