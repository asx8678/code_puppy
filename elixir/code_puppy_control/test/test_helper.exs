# CodePuppy Control Test Helper
#
# Integration tests:
#   mix test --exclude integration    # Skip integration tests (default)
#   mix test --only integration       # Run only integration tests
#   mix test --exclude e2e            # Skip E2E tests (default)
#   mix test --only e2e               # Run only E2E tests
#   mix test                          # Run all tests
#
# E2E tests:
#   mix test.e2e                      # Run E2E tests via custom task
#   SKIP_E2E=1 mix test              # Skip E2E tests
#   E2E_TIMEOUT=60000 mix test.e2e  # Override timeout (60s)

# Ensure support files are loaded (non-.ex support files)
Code.require_file("support/mock_python_worker.ex", __DIR__)
Code.require_file("support/e2e_case.ex", __DIR__)

# Support .ex files in test/support are automatically loaded via compilation
# This includes: test_reset.ex, stateful_case.ex, stdio_test_helper.ex

# Start parser registry for tests (bd-114: pure Elixir parsers)
# Registry may already be started by the application supervision tree
case CodePuppyControl.Parsing.ParserRegistry.start_link(
       name: CodePuppyControl.Parsing.ParserRegistry
     ) do
  {:ok, _registry} -> :ok
  {:error, {:already_started, _pid}} -> :ok
end

# Start callback registry for tests (bd-156)
case CodePuppyControl.Callbacks.Registry.start_link(name: CodePuppyControl.Callbacks.Registry) do
  {:ok, _pid} -> :ok
  {:error, {:already_started, _pid}} -> :ok
end

CodePuppyControl.Parsing.Parsers.register_all()

# Configure ExUnit with integration and E2E tests excluded by default
ExUnit.configure(
  exclude: [:integration, :e2e, :skip],
  formatters: [ExUnit.CLIFormatter],
  timeout: 30_000
)

# Use deterministic random for reproducible tests
:rand.seed(:exsss, {1, 2, 3})

ExUnit.start()
