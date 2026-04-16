# Mutmut Mutation Testing Configuration

This document describes mutation testing setup for pack_parallelism using [mutmut](https://github.com/boxed/mutmut).

## Installation

```bash
# Add mutmut to dev dependencies
uv add --dev mutmut

# Or with pip
pip install mutmut
```

## Configuration

Add to `pyproject.toml`:

```toml
[tool.mutmut]
paths_to_mutate = "code_puppy/plugins/pack_parallelism/"
backup = false
runner = "pytest tests/plugins/pack_parallelism/ -x --tb=short"
tests_dir = "tests/plugins/pack_parallelism/"
show_mutation_ids = true
```

## Usage

### Run Full Mutation Test

```bash
# Run mutation testing on pack_parallelism
cd /Users/adam2/projects/code_puppy-audit-ci-docs-batch-1
mutmut run --paths-to-mutate code_puppy/plugins/pack_parallelism/ --runner "pytest tests/plugins/pack_parallelism/ -x"
```

### Check Results

```bash
# Show results summary
mutmut results

# Show surviving mutants
mutmut results --status-survived

# Apply specific mutant to examine it
mutmut apply <mutation-id>
```

### CI Integration

For CI/CD pipelines, use a targeted check:

```bash
#!/bin/bash
# scripts/mutmut-check.sh - Run in CI with threshold

mutmut run --paths-to-mutate code_puppy/plugins/pack_parallelism/ \
    --runner "pytest tests/plugins/pack_parallelism/ -x --tb=short" \
    || true

# Check if mutation score meets threshold
SURVIVED=$(mutmut results --status-survived | wc -l)
if [ "$SURVIVED" -gt 5 ]; then
    echo "WARNING: $SURVIVED mutants survived. Consider improving tests."
    exit 0  # Non-blocking in CI
fi
```

## Targeted Mutation Areas

Priority modules for mutation testing:

1. **`run_limiter.py`** - Core concurrency control
   - Critical: `acquire_async()`, `release()`
   - Edge cases: `update_config()`, `force_reset_limiter_state()`

2. **`register_callbacks.py`** - Plugin integration
   - Hook registration logic
   - Command handling (`/pack-parallel`)

## Interpreting Results

### Acceptable Survivors

Some mutants may survive due to:
- Defensive code that handles impossible states
- Logging statements
- Error messages

### Actionable Survivors

Focus on fixing mutants in:
- Core business logic (semaphore management)
- Config validation
- State transitions

## Example Workflow

```bash
# 1. Run mutation tests
mutmut run --paths-to-mutate code_puppy/plugins/pack_parallelism/

# 2. Review surviving mutants
mutmut results --status-survived

# 3. Apply a mutant to examine
mutmut apply 123

# 4. Run tests to see failure
pytest tests/plugins/pack_parallelism/test_run_limiter.py -x

# 5. Undo the mutant
mutmut undo

# 6. Improve tests to catch the mutant, repeat
```
