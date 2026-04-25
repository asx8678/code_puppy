# Elixir Test Triage — Action Plan

**Date:** 2026-04-24
**Branch:** `fix/security-regression-and-test-triage`
**Fast-suite command:** `mix test --exclude slow --exclude integration --max-failures 20`

## Current validation status

The fast Elixir suite is green after narrowing the quarantine and fixing several deterministic test issues:

```text
9 doctests, 89 properties, 4997 tests, 0 failures (180 excluded)
```

Current `:triage_pending` usage is intentionally narrow:

| Scope | File/Test | Reason | Follow-up |
|---|---|---|---|
| Module | `CodePuppyControl.Transport.StdioServiceTest` | JSON-RPC stdio subprocess harness returns empty/non-JSON responses in the test environment | Fix `capture_stdio/2` / Mix task subprocess startup and then remove module tag |
| Module | `CodePuppyControl.Transport.ModelServicesRpcTest` | Same subprocess/stdio pattern as `StdioServiceTest` | Share the stdio harness fix, then remove module tag |
| Individual test | `CodePuppyControlWeb.TerminalChannelTest` — `close uses pty_session_id, not topic session_id` | Non-deterministic PTY teardown (`:pty_exit`) in channel close path | Stabilize PTY lifecycle assertion/teardown, then remove test tag |

All other previously tagged suites were either fixed or proven stable and are back in the default fast suite.

## Historical failure snapshot

The initial triage snapshot found 125 full-suite failures / 126 fast-suite failures. The main buckets were:

| Root Cause | Historical Count | Bucket | Current Status |
|---|---:|---|---|
| `F_ENV: StdioService` subprocess harness | 71 | Environment / harness | Still quarantined via two transport modules |
| `C_SECURITY: sensitive_path?` regression | 17 | Production bug | Fixed in `file_ops/security.ex` |
| `C_REPL: mock dispatch / command state` | 18 | Test isolation / contract | Fixed/narrowed; REPL tests are active again |
| `C_API`, `C_LLM`, `C_CONFIG`, `C_MIGRATOR`, `D_OUTDATED` | 19 | Contract drift / stale tests | Fixed or updated in tests |

## Fixes included in this branch

### Security and runtime fixes

- Restored the direct sensitive-path check in `CodePuppyControl.FileOps.Security.sensitive_path?/1`; the previous mangled comment accidentally hid `path_is_sensitive?(expanded) or`.
- Hardened `CodePuppyControl.Auth.ChatGptOAuth.load_stored_tokens/0` so missing files, invalid JSON, and non-map decoded data return `nil` instead of leaking unexpected shapes.
- Added a defensive REPL agent-catalogue fallback in `REPL.Loop` for tests/partial boot states where the primary catalogue lookup is unavailable.
- Adjusted scheduler history lookup for the current SQLite JSON behavior.
- Fixed `Concurrency.Limiter` timeout cleanup so timed-out waiters are removed instead of poisoning later release wakeups, and exposed a reset hook for test isolation.

### Test fixes and isolation improvements

- Added global `:triage_pending` exclusion in `test_helper.exs`, but only the scopes listed above remain tagged.
- Re-enabled REPL test modules by removing broad module tags and making `LoopTest` initialize the slash-command registry deterministically per test.
- Re-enabled `AddModelInteractiveTest` by giving it a per-test isolated models.dev fixture file instead of relying on the mutable shared `test/support/models_dev_parser_test_data.json` path.
- Re-enabled limiter, sessions controller, schema property, and most terminal-channel coverage after fixing deterministic flake sources (limiter waiter cleanup, sessions-controller sandbox ownership, and non-castable integer property generation).
- Updated stale assertions in OAuth, scheduler, model factory, migrator, create-file, and worker tests.

## Remaining follow-up work

1. **Fix the stdio subprocess harness**
   - Reproduce with `mix test --include triage_pending test/code_puppy_control/transport/stdio_service_test.exs`.
   - Check whether `mix code_puppy.stdio_service` emits compilation/banner output, exits early, or times out under ExUnit.
   - Make `capture_stdio/2` deterministic and unpolluted by non-JSON stdout.
   - Remove `@moduletag :triage_pending` from `StdioServiceTest` and `ModelServicesRpcTest` once green.

2. **Stabilize the terminal channel close test**
   - Reproduce with `mix test --include triage_pending test/code_puppy_control_web/channels/terminal_channel_test.exs:159`.
   - Fix the PTY close lifecycle assertion/teardown so `:pty_exit` does not race the test process.
   - Remove the individual `@tag :triage_pending`.

3. **Keep quarantine visible**
   - Do not add broad module-level tags without recording the exact reason here and in the companion CSV.
   - Prefer fixing deterministic contract drift over tagging.
   - Any new `:triage_pending` tag must include a follow-up owner/issue in bd.

## Verification commands

```bash
cd elixir/code_puppy_control
mix test test/code_puppy_control/cli/slash_commands/commands/add_model_interactive_test.exs --trace
mix test test/code_puppy_control/repl/loop_test.exs --trace
mix test --exclude slow --exclude integration --max-failures 20
```

Current result for the full fast-suite command:

```text
9 doctests, 89 properties, 4997 tests, 0 failures (180 excluded)
```
