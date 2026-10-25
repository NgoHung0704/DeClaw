# Python maintenance baseline — 2026-10-25

Scope: stabilize DB singleton initialization before Phase 9 detailed design.
The documentation/context-tool cleanup was committed separately as `5b35572`.
No gateway/UI feature, phase branch, dependency declaration or lockfile change.

## Defect and fix

`declaw/db/engine.py:get_sessionmaker` held a non-reentrant lock while calling
`get_engine`, which acquired that lock again if the engine had not been created.
CLI commands generally initialized the engine first and masked the order
requirement. Document-stack construction and `get_session` also use this factory.

Initialize the engine before entering the factory lock; preserve the second
singleton check inside the lock. The existing API and one-instance semantics
remain unchanged. No schema, transaction, session lifetime or migration changes.

## Regression evidence

Tests were added before implementation in `tests/unit/test_db.py`:

- `test_sessionmaker_can_initialize_before_engine`: initializes the factory
  first, checks stable identity and binding to the single engine.
- `test_concurrent_cold_factory_calls_share_one_engine_and_sessionmaker`: eight
  synchronized callers mix engine-first and factory-first access; engine and
  factory construction each occur once.

Each scenario runs in an isolated subprocess with a 15-second timeout, an
explicit temporary engine path and no user configuration/keyring access. A
regression cannot leave a locked worker or singleton state inside pytest.

Before fix: **2 failed** by subprocess timeout, 8 DB tests deselected.
After fix: **10 DB tests passed** in 5.64 seconds.

## Full baseline

- `uv sync --frozen`: passed. It removed 43 packages outside the frozen dependency
  set from the existing environment and rebuilt the editable DeClaw package;
  `pyproject.toml` and `uv.lock` remain unchanged. Cross-drive hardlink fallback
  caused a performance warning, not a dependency-resolution failure.
- `uv run ruff check .`: passed.
- `uv run mypy declaw declaw_plugin_sdk`: passed, 100 source files.
- Full pytest: **786 passed, 1 skipped** in 154.20 seconds. The sole skip was
  `tests/unit/test_tools_filesystem.py:109`: symlinks are not supported in this
  environment. No Ollama readiness skip occurred; this is integration coverage,
  not a new model-quality or performance benchmark.
- Post-fix documentation source guards: **2,226 tests passed**.
- Local link checks: 44 targets resolved across the changed current/report
  documents. `git diff --check` passed. The user settings SHA-256 matched the
  pre-work value; no user settings content was staged.

The full test invocation uses `uv run --project <checkout> pytest <checkout>/tests
-q -ra --tb=short --basetemp <fresh writable directory>
-o faulthandler_timeout=60` from outside the checkout. This avoids loading the
repository .env and avoids the system temp permission issue encountered earlier.
Windows asyncio tests require execution outside this environment's sandbox.
Live Ollama integration tests retain their own normal readiness/skip checks.

User `.claude/settings.json` is excluded from both commits and must keep its
original working-tree contents. No push, publication or external deployment.
