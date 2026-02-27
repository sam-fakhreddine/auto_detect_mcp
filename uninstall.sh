#!/usr/bin/env bash
set -euo pipefail

HOOK_DEST="$HOME/.claude/hooks/auto_detect_mcp.py"
CONFIG_DIR="$HOME/.config/auto-detect-mcp"
SETTINGS="$HOME/.claude/settings.json"
CACHE_DIR="$HOME/.claude/auto-detect-mcp-cache"
HOOK_CMD="python3 $HOME/.claude/hooks/auto_detect_mcp.py"

echo "Uninstalling auto-detect-mcp..."

# ── Hook file ─────────────────────────────────────────────────────────────────
if [[ -f "$HOOK_DEST" ]]; then
  rm "$HOOK_DEST"
  echo "  ✓ Removed $HOOK_DEST"
else
  echo "  - Hook file not found, skipping"
fi

# ── Config directory ──────────────────────────────────────────────────────────
if [[ -d "$CONFIG_DIR" ]]; then
  read -r -p "  Remove config directory $CONFIG_DIR? [y/N] " confirm
  if [[ "$confirm" =~ ^[Yy]$ ]]; then
    rm -rf "$CONFIG_DIR"
    echo "  ✓ Removed $CONFIG_DIR"
  else
    echo "  - Skipping config directory"
  fi
fi

# ── Marker cache ──────────────────────────────────────────────────────────────
if [[ -d "$CACHE_DIR" ]]; then
  rm -rf "$CACHE_DIR"
  echo "  ✓ Removed marker cache"
fi

# ── settings.json ─────────────────────────────────────────────────────────────
if [[ -f "$SETTINGS" ]] && command -v python3 >/dev/null 2>&1; then
  cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"
  HOOK_CMD="$HOOK_CMD" SETTINGS_PATH="$SETTINGS" python3 - <<'PYEOF'
import json, os, sys
from pathlib import Path

settings_path = Path(os.environ["SETTINGS_PATH"])
hook_cmd = os.environ["HOOK_CMD"]

try:
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
except Exception as e:
    print(f"Error reading {settings_path}: {e}", file=sys.stderr)
    sys.exit(1)

ups = settings.get("hooks", {}).get("UserPromptSubmit", [])
changed = False
for entry in ups:
    before = len(entry.get("hooks", []))
    entry["hooks"] = [h for h in entry.get("hooks", []) if h.get("command") != hook_cmd]
    if len(entry["hooks"]) != before:
        changed = True

if changed:
    try:
        settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        print("  ✓ Hook removed from settings.json")
    except OSError as e:
        print(f"Error writing {settings_path}: {e}", file=sys.stderr)
        sys.exit(1)
else:
    print("  - Hook not found in settings.json")
PYEOF
fi

echo ""
echo "Uninstall complete."
