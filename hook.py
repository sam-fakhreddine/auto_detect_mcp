#!/usr/bin/env python3
"""
auto-detect-mcp — UserPromptSubmit hook for Claude Code.

Runs once per session. Scans the project for signals defined in
~/.config/auto-detect-mcp/configs/*.json and writes .mcp.json if
any match. Silent when nothing is detected.
"""
import sys
import json
import os
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "auto-detect-mcp" / "configs"
MARKER_DIR = Path.home() / ".claude" / "auto-detect-mcp-cache"


def load_configs() -> list[dict]:
    if not CONFIG_DIR.exists():
        return []
    configs = []
    for f in CONFIG_DIR.glob("*.json"):
        try:
            configs.append(json.loads(f.read_text()))
        except Exception:
            pass
    return configs


def check_signals(signals: dict, cwd: Path) -> list[str]:
    found = []

    for fname in signals.get("files", []):
        if (cwd / fname).exists():
            found.append(fname)

    for pattern in signals.get("globs", []):
        if any(cwd.rglob(pattern)):
            found.append(pattern)

    pkg_keywords: dict = signals.get("package_keywords", {})
    for manifest, keywords in pkg_keywords.items():
        path = cwd / manifest
        if not path.exists():
            continue
        content = path.read_text().lower()
        if manifest == "package.json":
            try:
                data = json.loads(content)
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                for kw in keywords:
                    if any(kw.lower() in k for k in deps):
                        found.append(f"{manifest}({kw})")
                        break
            except Exception:
                pass
        else:
            for kw in keywords:
                if kw.lower() in content:
                    found.append(f"{manifest}({kw})")
                    break

    return found


def merge_mcp_json(cwd: Path, new_servers: dict) -> None:
    mcp_path = cwd / ".mcp.json"
    existing = {}
    if mcp_path.exists():
        try:
            existing = json.loads(mcp_path.read_text())
        except Exception:
            pass

    merged_servers = {**existing.get("mcpServers", {}), **new_servers}
    existing["mcpServers"] = merged_servers
    mcp_path.write_text(json.dumps(existing, indent=2))


def main():
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    session_id = hook_input.get("session_id", "")
    cwd = Path(hook_input.get("cwd", os.getcwd()))

    if not session_id:
        sys.exit(0)

    MARKER_DIR.mkdir(parents=True, exist_ok=True)
    marker = MARKER_DIR / session_id

    if marker.exists():
        sys.exit(0)

    marker.touch()

    markers = sorted(MARKER_DIR.iterdir(), key=lambda p: p.stat().st_mtime)
    for old in markers[:-100]:
        old.unlink(missing_ok=True)

    configs = load_configs()
    if not configs:
        sys.exit(0)

    matched_servers: dict = {}
    matched_labels: list[str] = []

    for config in configs:
        signals_found = check_signals(config.get("signals", {}), cwd)
        if signals_found:
            matched_servers.update(config.get("mcpServers", {}))
            label = config.get("name", "unknown")
            matched_labels.append(f"{label}({', '.join(signals_found)})")

    if not matched_servers:
        sys.exit(0)

    mcp_path = cwd / ".mcp.json"
    existing_servers: set = set()
    if mcp_path.exists():
        try:
            existing = json.loads(mcp_path.read_text())
            existing_servers = set(existing.get("mcpServers", {}).keys())
        except Exception:
            pass

    new_servers = {k: v for k, v in matched_servers.items() if k not in existing_servers}
    if not new_servers:
        sys.exit(0)

    merge_mcp_json(cwd, new_servers)

    print(
        f"[auto-detect-mcp] Detected: {', '.join(matched_labels)}. "
        f"Added {len(new_servers)} server(s) to .mcp.json "
        f"({', '.join(new_servers.keys())}). "
        f"Run /restart to activate."
    )


if __name__ == "__main__":
    main()
