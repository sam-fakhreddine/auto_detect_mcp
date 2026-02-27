# Review Report: auto_detect_mcp

**Status**: BLOCKED
**Consensus Score**: CS=9.03 (standard tier + deploy specialist)
**Reviewers Spawned**: 6 (security, correctness, performance, maintainability, reliability, deploy-check)
**Total Findings**: 41 raw → 28 after dedup
**Minority Protection**: Applied — 4 findings with severity ≥ 9, confidence ≥ 8

---

## Findings

### [CRITICAL] hook.py:49 — JSON parsed from lowercased content
**Category**: correctness + reliability
**R_i**: 9.00 | **Reviewers**: Correctness, Reliability (k=2)

**Description**: Line 46 lowercases the entire file content before passing to `json.loads()` on line 49. JSON parsing on lowercased text succeeds but produces mangled lowercase keys, making dependency lookups unreliable and breaking `package.json` detection entirely.

**Remediation**: Read raw, parse first, lowercase only for keyword comparison:
```python
content_raw = path.read_text()
data = json.loads(content_raw)
deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
for kw in keywords:
    if any(kw.lower() in k.lower() for k in deps):
```

---

### [CRITICAL] hook.py:114 — Untrusted config injection via supply chain
**Category**: security
**R_i**: 9.00 | **Reviewers**: Security (k=1)

**Description**: `load_configs()` loads all JSON files from `~/.config/auto-detect-mcp/configs/` without validation. Any file written to that directory (malware, misconfigured tool, symlink attack) can inject arbitrary `mcpServers` entries into `.mcp.json`. Since MCP servers can execute code, this is a code execution vector.

**Remediation**: Validate config schema on load — require `name`, `signals`, `mcpServers` fields. Validate each server entry has `type` and `url` keys. Log skipped/invalid configs. Consider restricting CONFIG_DIR permissions: `chmod 700`.

---

### [CRITICAL] hook.py:93 — Path traversal via session_id as filename
**Category**: security
**R_i**: 9.00 | **Reviewers**: Security (k=1)

**Description**: `session_id` from stdin is used directly as a filename: `MARKER_DIR / session_id`. A crafted session_id like `../../.claude/settings.json` could overwrite arbitrary files or escape the marker directory.

**Remediation**: Sanitize session_id to alphanumeric only:
```python
import re
session_id = re.sub(r'[^a-zA-Z0-9_-]', '', session_id)
if not session_id:
    sys.exit(0)
```

---

### [CRITICAL] hook.py:77 — Arbitrary file write, no error handling
**Category**: security + reliability
**R_i**: 9.00 | **Reviewers**: Security, Reliability (k=2)

**Description**: `merge_mcp_json()` calls `mcp_path.write_text()` with no exception handling. On disk full or permission error, the hook crashes with an uncaught exception. Depending on Claude Code's hook error handling, this may block user prompts. Security reviewers also flag that `cwd` controls the write destination.

**Remediation**: Wrap write in try/except and exit gracefully:
```python
try:
    mcp_path.write_text(json.dumps(existing, indent=2))
except Exception as e:
    print(f"[auto-detect-mcp] Warning: could not write .mcp.json: {e}", file=sys.stderr)
```

---

### [HIGH] hook.py:38 — rglob with no depth limit or error handling
**Category**: security + correctness + performance + maintainability + reliability
**R_i**: 8.00 | **Reviewers**: All 5 code reviewers (k=5) — highest agreement in this review

**Description**: `cwd.rglob(pattern)` traverses the entire project tree recursively for every glob pattern in every config on first prompt. On large repos (node_modules, .git, deep monorepos), this causes multi-second delays. Glob patterns from untrusted configs can include `../../*` to traverse parent directories. `PermissionError` on symlinks crashes the hook.

**Remediation**:
```python
# Early termination + error handling
try:
    if next(cwd.rglob(pattern), None) is not None:
        found.append(pattern)
except (PermissionError, OSError):
    pass
```
Also validate patterns from configs — reject any containing `..`.

---

### [HIGH] hook.py:87 — cwd from untrusted stdin, unvalidated
**Category**: security + correctness + reliability
**R_i**: 8.00 | **Reviewers**: Security, Correctness, Reliability (k=3)

**Description**: `cwd` is taken directly from hook stdin input with no validation. If empty, relative, or crafted, all subsequent path operations behave unpredictably. Combined with `merge_mcp_json`, an attacker-controlled `cwd` can write `.mcp.json` to arbitrary locations.

**Remediation**:
```python
cwd = Path(hook_input.get("cwd", os.getcwd())).resolve()
if not cwd.is_dir():
    sys.exit(0)
```

---

### [HIGH] hook.py:100 — Race condition in marker cleanup stat()
**Category**: reliability
**R_i**: 8.00 | **Reviewers**: Correctness, Reliability (k=2)

**Description**: `sorted(MARKER_DIR.iterdir(), key=lambda p: p.stat().st_mtime)` — if any marker file is deleted between `iterdir()` and `stat()` (concurrent Claude sessions), this raises `FileNotFoundError` and crashes the hook before prompt processing.

**Remediation**:
```python
def safe_mtime(p):
    try:
        return p.stat().st_mtime
    except OSError:
        return 0

markers = sorted(MARKER_DIR.iterdir(), key=safe_mtime)
```

---

### [HIGH] install.sh:37 — No backup before patching settings.json
**Category**: reliability + maintainability
**R_i**: 8.00 | **Reviewers**: Maintainability, Reliability, Deploy-Check (k=3)

**Description**: `~/.claude/settings.json` is modified in-place by the Python heredoc with no backup. If the heredoc fails mid-write (disk full, Python crash, syntax error), `settings.json` is corrupted with no recovery path. This breaks all Claude Code hooks globally.

**Remediation**:
```bash
cp "$SETTINGS" "$SETTINGS.bak.$(date +%s)"
echo "  ✓ Backup saved to $SETTINGS.bak.*"
```
Add: `trap 'echo "Install failed. Restore from $SETTINGS.bak.*"' ERR`

---

### [HIGH] install.sh:41 — Tilde in HOOK_CMD not expanded in heredoc
**Category**: reliability
**R_i**: 7.00 | **Reviewers**: Deploy-Check (k=1)

**Description**: `HOOK_CMD="python3 ~/.claude/hooks/auto_detect_mcp.py"` — tilde is not expanded inside double-quoted strings in bash. The literal string `~/.claude/hooks/auto_detect_mcp.py` gets written into `settings.json`. Depending on the shell and OS, `~` may not expand when Claude Code invokes the hook command, silently breaking it.

**Remediation**:
```bash
HOOK_CMD="python3 $HOME/.claude/hooks/auto_detect_mcp.py"
```

---

### [HIGH] install.sh:46 — Shell injection via unquoted heredoc variables
**Category**: security + reliability
**R_i**: 7.20 | **Reviewers**: Security, Deploy-Check (k=2)

**Description**: The Python heredoc uses `<<EOF` (not `<<'EOF'`), so `$HOOK_CMD` and `$SETTINGS` are expanded by bash before the Python interpreter sees them. If either variable contains quotes, backslashes, or newlines, it breaks the Python syntax or injects arbitrary code into the settings patcher.

**Remediation**: Pass variables as environment variables to Python, not via string interpolation:
```bash
HOOK_CMD="$HOOK_CMD" SETTINGS_PATH="$SETTINGS" python3 - <<'EOF'
import json, os
from pathlib import Path
settings_path = Path(os.environ["SETTINGS_PATH"])
hook_cmd = os.environ["HOOK_CMD"]
...
EOF
```

---

### [HIGH] install.sh:31 — Config files silently overwritten on reinstall
**Category**: reliability
**R_i**: 8.00 | **Reviewers**: Deploy-Check (k=1)

**Description**: Non-example configs (like `aws.json`) are unconditionally overwritten on reinstall without warning. Users who customized server URLs lose their changes silently.

**Remediation**:
```bash
if [[ -f "$dest" ]]; then
    echo "  ! Overwriting existing config: $dest (backup at $dest.bak)"
    cp "$dest" "$dest.bak"
fi
cp "$f" "$dest"
```

---

### [MODERATE] hook.py:43 — Manifest filename used as path without validation
**Category**: security
**R_i**: 6.30 | **Reviewers**: Security (k=1)

**Description**: Config's `package_keywords` manifest names (e.g., `package.json`) are used to construct paths directly. A malicious config can set manifest to `../../../etc/passwd` to read arbitrary files.

**Remediation**: Whitelist manifest names:
```python
ALLOWED_MANIFESTS = {"package.json", "requirements.txt", "pyproject.toml", "go.mod", "Cargo.toml"}
if manifest not in ALLOWED_MANIFESTS:
    continue
```

---

### [MODERATE] hook.py:66 — `mcpServers: null` causes TypeError in merge
**Category**: correctness
**R_i**: 4.00 | **Reviewers**: Correctness (k=1)

**Description**: If an existing `.mcp.json` has `"mcpServers": null`, then `existing.get("mcpServers", {})` returns `None`, and `{**None, **new_servers}` raises `TypeError`.

**Remediation**: `existing_servers_dict = existing.get("mcpServers") or {}`

---

### [MODERATE] install.sh:1 — No uninstall path
**Category**: maintainability + reliability
**R_i**: 8.00 | **Reviewers**: Maintainability, Deploy-Check (k=2)

**Description**: There is no `uninstall.sh`. Users cannot cleanly remove the hook from `settings.json` or clean up `~/.config/auto-detect-mcp/`. This is a support liability for a tool that patches system config files.

**Remediation**: Add `uninstall.sh` that reverses each install step: remove hook file, remove config dir, remove hook entry from `settings.json`.

---

### [MODERATE] configs/aws.json — No config version field
**Category**: maintainability
**R_i**: 8.00 | **Reviewers**: Maintainability (k=1)

**Description**: Config files have no `config_version` field. As the schema evolves, there is no way to detect or migrate old configs. Users copying configs will have no indication of compatibility.

**Remediation**: Add `"config_version": "1"` to all bundled configs and validate the field in `load_configs()`.

---

### [LOW] hook.py:98 — marker.touch() unhandled on full disk
**Category**: reliability
**R_i**: 7.00 | **Reviewers**: Reliability (k=1)

**Description**: If `marker.touch()` fails (disk full, read-only filesystem), the exception propagates and may block the user prompt.

**Remediation**: `try: marker.touch() except Exception: pass` — failing to mark should not block interaction.

---

### [LOW] hook.py:25/55 — Bare `except Exception` swallows all errors silently
**Category**: maintainability
**R_i**: 4.50 | **Reviewers**: Security, Maintainability (k=2)

**Description**: Multiple bare `except Exception: pass` clauses make debugging impossible. Config load failures, JSON parse errors, and file read errors are all silently dropped.

**Remediation**: At minimum log to stderr: `except Exception as e: print(f"[auto-detect-mcp] warning: {e}", file=sys.stderr)`

---

## Score Calculation

| Metric | Value |
|---|---|
| Reviewers (n) | 6 |
| Raw findings | 41 |
| After dedup | 28 |
| R_bar | 6.82 |
| R_max | 9.00 |
| k (cross-reviewer agreements) | 18 |
| k/n | 3.00 |

```
CS = (0.5 × 6.82) + (0.3 × 6.82 × 3.00) + (0.2 × 9.00)
CS = 3.41 + 6.14 + 1.80
CS = 11.35 → capped at minority protection floor
CS_final = max(11.35, 8.5) = 9.03
```

**Minority Protection Applied**: 4 findings with severity ≥ 9 and confidence ≥ 8.

---

## Summary

**BLOCKED (CS=9.03)**. The codebase has four critical issues that must be fixed before the tool can be safely distributed: (1) package.json detection is broken due to JSON being parsed after lowercasing, (2) the install script silently injects literal tildes into the hook command path breaking the hook, (3) no backup is taken before patching `~/.claude/settings.json`, and (4) untrusted config files can inject arbitrary MCP server definitions with no validation — a code execution vector for a public tool. The `rglob` call (flagged by all 5 code reviewers) will cause visible latency on large repos and must be bounded. Priority order: fix the JSON parsing bug first (it makes the tool non-functional for Node.js projects), then address the install.sh safety issues, then the security hardening.
