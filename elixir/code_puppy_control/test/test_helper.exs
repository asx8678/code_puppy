# CodePuppy Control Test Helper
#
# Integration tests:
#   mix test --exclude integration    # Skip integration tests (default)
#   mix test --only integration       # Run only integration tests
#   mix test                          # Run all tests

# Ensure support files are loaded
Code.require_file("support/mock_python_worker.ex", __DIR__)

# Support file is automatically loaded via compilation

# Configure ExUnit with integration tests excluded by default
ExUnit.start(
  exclude: [:integration],
  timeout: 30_000
)
