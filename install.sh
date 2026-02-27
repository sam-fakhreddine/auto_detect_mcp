#!/usr/bin/env bash
set -euo pipefail

HOOK_DEST="$HOME/.claude/hooks/auto_detect_mcp.py"
CONFIG_DIR="$HOME/.config/auto-detect-mcp/configs"
SETTINGS="$HOME/.claude/settings.json"

echo "Installing auto-detect-mcp..."

# Copy hook
mkdir -p "$HOME/.claude/hooks"
cp hook.py "$HOOK_DEST"
chmod +x "$HOOK_DEST"
echo "  ✓ Hook installed to $HOOK_DEST"

# Install configs
mkdir -p "$CONFIG_DIR"
for f in configs/*.json; do
  name=$(basename "$f")
  # Skip example configs (prefixed with "example-")
  if [[ "$name" == example-* ]]; then
    dest="$CONFIG_DIR/$name"
    if [[ ! -f "$dest" ]]; then
      cp "$f" "$dest"
      echo "  ✓ Example config installed: $dest"
    else
      echo "  - Skipping existing: $dest"
    fi
  else
    dest="$CONFIG_DIR/$name"
    cp "$f" "$dest"
    echo "  ✓ Config installed: $dest"
  fi
done

# Patch settings.json
if [[ ! -f "$SETTINGS" ]]; then
  echo '{"hooks":{"UserPromptSubmit":[]}}' > "$SETTINGS"
fi

HOOK_CMD="python3 ~/.claude/hooks/auto_detect_mcp.py"

if grep -q "auto_detect_mcp" "$SETTINGS"; then
  echo "  - Hook already registered in $SETTINGS, skipping"
else
  python3 - <<EOF
import json, sys
from pathlib import Path

settings_path = Path("$SETTINGS")
settings = json.loads(settings_path.read_text())

settings.setdefault("hooks", {}).setdefault("UserPromptSubmit", [])

# Find existing catch-all matcher or create one
ups = settings["hooks"]["UserPromptSubmit"]
target = next((h for h in ups if h.get("matcher") == ""), None)
if target is None:
    target = {"matcher": "", "hooks": []}
    ups.append(target)

target["hooks"].append({"type": "command", "command": "$HOOK_CMD"})
settings_path.write_text(json.dumps(settings, indent=2))
print("  ✓ Hook registered in $SETTINGS")
EOF
fi

echo ""
echo "Done. Add your own configs to: $CONFIG_DIR"
echo "On the next Claude Code session in an AWS repo, .mcp.json will be auto-written."
