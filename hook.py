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
import re
import tomllib
from pathlib import Path

CONFIG_DIR = Path(os.getenv("AUTO_DETECT_MCP_CONFIG_DIR",
                             str(Path.home() / ".config" / "auto-detect-mcp" / "configs")))
MARKER_DIR = Path(os.getenv("AUTO_DETECT_MCP_CACHE_DIR",
                             str(Path.home() / ".claude" / "auto-detect-mcp-cache")))
MARKER_KEEP = int(os.getenv("AUTO_DETECT_MCP_KEEP_MARKERS", "100"))

ALLOWED_MANIFESTS = {
    "package.json", "requirements.txt", "pyproject.toml",
    "go.mod", "Cargo.toml", "Gemfile",
}

REQUIRED_CONFIG_FIELDS = {"name", "signals", "mcpServers"}


def warn(msg: str) -> None:
    print(f"[auto-detect-mcp] {msg}", file=sys.stderr)


def validate_config(config: dict, source: str) -> bool:
    missing = REQUIRED_CONFIG_FIELDS - set(config.keys())
    if missing:
        warn(f"Skipping {source}: missing fields {missing}")
        return False
    if not isinstance(config.get("mcpServers"), dict):
        warn(f"Skipping {source}: 'mcpServers' must be an object")
        return False
    for name, server in config["mcpServers"].items():
        if not isinstance(server, dict) or "url" not in server:
            warn(f"Skipping {source}: server '{name}' missing 'url'")
            return False
    return True


def load_configs() -> list:
    if not CONFIG_DIR.exists():
        return []
    configs = []
    for f in CONFIG_DIR.glob("*.toml"):
        try:
            data = tomllib.loads(f.read_text(encoding="utf-8"))
            if validate_config(data, f.name):
                configs.append(data)
        except tomllib.TOMLDecodeError as e:
            warn(f"Skipping {f.name}: invalid TOML ({e})")
        except OSError as e:
            warn(f"Skipping {f.name}: read error ({e})")
    return configs


def check_signals(signals: dict, cwd: Path) -> list:
    found = []

    for fname in signals.get("files", []):
        if ".." in str(fname) or str(fname).startswith("/"):
            continue
        try:
            if (cwd / fname).exists():
                found.append(fname)
        except OSError:
            pass

    for pattern in signals.get("globs", []):
        if ".." in str(pattern):
            continue
        try:
            if next(cwd.rglob(pattern), None) is not None:
                found.append(pattern)
        except (PermissionError, OSError):
            pass

    for manifest, keywords in signals.get("package_keywords", {}).items():
        if manifest not in ALLOWED_MANIFESTS:
            continue
        path = cwd / manifest
        if not path.exists():
            continue
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if manifest == "package.json":
            try:
                data = json.loads(raw)
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                for kw in keywords:
                    if any(kw.lower() in k.lower() for k in deps):
                        found.append(f"{manifest}({kw})")
                        break
            except json.JSONDecodeError:
                pass
        else:
            content_lower = raw.lower()
            for kw in keywords:
                if kw.lower() in content_lower:
                    found.append(f"{manifest}({kw})")
                    break

    return found


def detect_matches(configs: list, cwd: Path):
    matched_servers = {}
    matched_labels = []
    for config in configs:
        signals_found = check_signals(config.get("signals", {}), cwd)
        if signals_found:
            matched_servers.update(config.get("mcpServers", {}))
            label = config.get("name", "unknown")
            matched_labels.append(f"{label}({', '.join(signals_found)})")
    return matched_servers, matched_labels


def get_new_servers(matched_servers: dict, cwd: Path) -> dict:
    mcp_path = cwd / ".mcp.json"
    existing_keys: set = set()
    if mcp_path.exists():
        try:
            existing = json.loads(mcp_path.read_text(encoding="utf-8", errors="replace"))
            existing_keys = set((existing.get("mcpServers") or {}).keys())
        except (json.JSONDecodeError, OSError):
            pass
    return {k: v for k, v in matched_servers.items() if k not in existing_keys}


def merge_mcp_json(cwd: Path, new_servers: dict) -> None:
    mcp_path = cwd / ".mcp.json"
    existing: dict = {}
    if mcp_path.exists():
        try:
            existing = json.loads(mcp_path.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError) as e:
            warn(f".mcp.json unreadable ({e}), will overwrite")
    existing["mcpServers"] = {**(existing.get("mcpServers") or {}), **new_servers}
    try:
        mcp_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except OSError as e:
        warn(f"Could not write .mcp.json: {e}")
        raise


def prune_markers() -> None:
    def safe_mtime(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0
    try:
        markers = sorted(MARKER_DIR.iterdir(), key=safe_mtime)
        for old in markers[:-MARKER_KEEP]:
            old.unlink(missing_ok=True)
    except (FileNotFoundError, PermissionError, OSError):
        pass


def main() -> None:
    try:
        hook_input = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    session_id = re.sub(r"[^a-zA-Z0-9_-]", "", hook_input.get("session_id", ""))
    if not session_id:
        sys.exit(0)

    try:
        cwd = Path(hook_input.get("cwd", os.getcwd())).resolve()
        if not cwd.is_dir():
            sys.exit(0)
    except (OSError, ValueError):
        sys.exit(0)

    try:
        MARKER_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        sys.exit(0)

    marker = MARKER_DIR / session_id
    if marker.exists():
        sys.exit(0)

    try:
        marker.touch()
    except OSError:
        pass

    prune_markers()

    configs = load_configs()
    if not configs:
        sys.exit(0)

    matched_servers, matched_labels = detect_matches(configs, cwd)
    if not matched_servers:
        sys.exit(0)

    new_servers = get_new_servers(matched_servers, cwd)
    if not new_servers:
        sys.exit(0)

    try:
        merge_mcp_json(cwd, new_servers)
    except OSError:
        sys.exit(0)

    print(
        f"[auto-detect-mcp] Detected: {', '.join(matched_labels)}. "
        f"Added {len(new_servers)} server(s) to .mcp.json "
        f"({', '.join(new_servers.keys())}). "
        f"Run /restart to activate."
    )


if __name__ == "__main__":
    main()
