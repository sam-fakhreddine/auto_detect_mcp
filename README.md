# auto-detect-mcp

A [Claude Code](https://claude.ai/claude-code) hook that automatically detects when a project needs MCP servers and writes `.mcp.json` so they load on the next session — without burning context tokens in repos that don't need them.

## The Problem

MCP server tool definitions consume context on every request (~2K–6K tokens per server). If you work across many repos, paying that cost everywhere — even in projects that never use those tools — is wasteful.

## How It Works

A `UserPromptSubmit` hook runs **once per session**. It scans the project for signals (config files, package dependencies, file patterns) and writes `.mcp.json` if a match is found. On the next `/restart`, the servers load automatically.

```
New session in a repo
        ↓
Hook fires on first prompt
        ↓
Scans for signals (cdk.json, *.tf, boto3 in requirements.txt, ...)
        ↓  match found
Writes .mcp.json → "Run /restart to activate"
        ↓  /restart
MCP servers loaded — tools available
```

If `.mcp.json` already exists and contains the detected servers, the hook is silent. Fully idempotent.

## Install

```bash
git clone https://github.com/sam-fakhreddine/auto_detect_mcp
cd auto_detect_mcp
bash install.sh
```

That's it. No dependencies beyond Python 3.12+ (stdlib only).

## Adding Your Own Configs

Drop a `.toml` file in `~/.config/auto-detect-mcp/configs/`:

```toml
config_version = "1"
name = "my-tooling"
description = "MCP servers for my tooling"

[signals]
files = ["my-config.json"]
globs = ["**/*.myext"]

[signals.package_keywords]
"package.json"     = ["my-package"]
"requirements.txt" = ["my-lib"]

[mcpServers.my-server]
type = "http"
url  = "https://my-mcp-server.example.com/mcp"
```

Multiple configs can coexist. If more than one matches, their `mcpServers` are merged into `.mcp.json`.

## Bundled Configs

### `aws.toml`

Detects AWS infrastructure projects and loads three MCP servers:

| Server | Purpose | Source |
|---|---|---|
| `aws-documentation` | Latest AWS docs and API references | [awslabs/mcp](https://github.com/awslabs/mcp/tree/main/src/aws-documentation-mcp-server) |
| `aws-iac` | CloudFormation docs, CDK best practices, construct examples | [awslabs/mcp](https://github.com/awslabs/mcp/tree/main/src/aws-iac-mcp-server) |
| `aws-diagram` | Generate architecture diagrams and technical illustrations | [awslabs/mcp](https://github.com/awslabs/mcp/tree/main/src/aws-diagram-mcp-server) |

**Signals detected:**

- Files: `cdk.json`, `samconfig.toml`, `template.yaml`, `serverless.yml`, `.aws-sam`
- Globs: `**/*.tf`, `**/*.tfvars`
- Packages: `aws-cdk-lib`, `@aws-sdk/*`, `boto3`, `aws-lambda-powertools` (across `package.json`, `requirements.txt`, `pyproject.toml`, `go.mod`)

> The bundled `aws.toml` uses placeholder URLs. Update them to point to your own self-hosted MCP server instance.

## Manual Override

The hook never overwrites servers already in `.mcp.json`. To opt a project out, add an empty `.mcp.json`:

```json
{ "mcpServers": {} }
```

To force a re-scan within a session, delete the marker:

```bash
rm ~/.claude/auto-detect-mcp-cache/<session-id>
```

## How the Once-Per-Session Guard Works

On first run, the hook writes a marker file at `~/.claude/auto-detect-mcp-cache/{session_id}`. Every subsequent prompt in that session hits the marker check and exits immediately — no filesystem scanning, no overhead.

Old markers are pruned automatically (keeps last 100).

## License

MIT
