# Coding-agent context tools

## Installed layout

Serena 2.1.0 is a development tool in `.agent-tools/`, with its own Python 3.13,
environment, cache and Serena home. It does not modify `pyproject.toml`, `uv.lock`
or the product virtual environment. `.serena/project.yml` is the shared Python
navigation configuration. Generated state and local binaries stay out of Git.
The configured MCP launch disables Serena usage reporting and automatic dashboard
windows. This does not alter the coding model provider's own data handling.

`scripts/setup-agent-tools.ps1` installs this pinned version and creates a local,
project-scoped `.codex/config.toml` for Serena and Context7. Run it with PowerShell
on a new Windows checkout. It preserves other project settings and refuses to
overwrite existing Serena/Context7 tables. Paths are generated for that checkout;
rerun/reconfigure after moving it. `uv` and network access are prerequisites.

Codex only loads project configuration for trusted projects. Start a new Codex
session (or restart the app) after setup, and use `/mcp` to confirm the two servers
are connected. A successful standalone smoke test does not prove an existing
chat has reloaded its tool catalog.

## Everyday use

- Start at `AGENTS.md`, then current status and the relevant code-map row.
- Serena is launched with an explicit project path, Codex context and individual
  tools. Use symbol lookup and references before reading whole Python files.
- Use normal text search for configuration/prose. Only Python navigation is
  configured now; add other language servers when there is actual source to work
  on and validate each one separately.
- Versioned status/decisions are durable knowledge. Serena memories are optional
  caches; do not use stale memories to override code or approved decisions.
- Context7 is remote library documentation retrieval, not an index of DeClaw.
  Query library names, versions and minimal API questions. Do not include private
  documents, credentials or whole source files. No API key is stored by this setup;
  rate/authentication limits may require account setup later. Use primary upstream
  docs when Context7 is unavailable.

For Claude Code, `CLAUDE.md` imports the shared `AGENTS.md`. Other agents should
use that same file as their project entry point; configure MCP through each
client's supported mechanism rather than copying Codex TOML into another format.

## Verify / troubleshoot

```powershell
$env:SERENA_HOME = "$PWD\.agent-tools\serena-home"
$env:PYTHONUTF8 = '1'
$env:SERENA_USAGE_REPORTING = 'false'
$env:UV_TOOL_DIR = "$PWD\.agent-tools\tools"
$env:UV_TOOL_BIN_DIR = "$PWD\.agent-tools\bin"
$env:UV_CACHE_DIR = "$PWD\.agent-tools\cache"
$env:UV_PYTHON_INSTALL_DIR = "$PWD\.agent-tools\python"
.agent-tools\bin\serena.exe project health-check "$PWD"
```

The health check exercises code navigation. It is not a DeClaw product test. Logs are local under
`.serena/logs/health-checks/`. A first language-server launch may download its
dependencies; subsequent launches reuse the cache.

## Verification on 2026-10-25

- Serena 2.1.0 health check passed on this Windows checkout, including symbol
  overview, lookup and reference search.
- A standalone MCP client using the project configuration successfully invoked
  `get_symbols_overview`, `find_symbol` and `find_referencing_symbols` on
  `build_document_stack`; references included the CLI chat and index paths.
- Context7 MCP initialized, listed `resolve-library-id` and `query-docs`, and
  resolved a public LangGraph documentation query without a stored API key.
- `codex mcp get serena --json` recognized the enabled project server and its
  absolute command, project path and environment.
- Local Markdown links and preservation of the historical context were checked;
  `git diff --check` passed. Product tests were not run for these documentation
  and developer-tool configuration changes.

This verifies standalone tool operation, not loading into the already-running
chat. Confirm the active servers with `/mcp` in a new trusted project session.

Official references: [Serena client configuration](https://oraios.github.io/serena/02-usage/030_clients.html),
[Codex MCP configuration](https://developers.openai.com/codex/mcp),
[Context7](https://github.com/upstash/context7).
