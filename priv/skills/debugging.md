---
name: debugging
description: Systematic debugging and troubleshooting techniques for finding and fixing bugs efficiently
version: 1.0.0
author: Mana Team
tags: debugging, troubleshooting, diagnostics, bug-fixing, root-cause
---

# Debugging & Troubleshooting Skill

Expert guidance for systematically finding and fixing bugs.

## When to Use

Activate this skill when:
- Investigating a bug or unexpected behavior
- Diagnosing production incidents
- Tracing the root cause of a failure
- Debugging performance issues
- Troubleshooting build or deployment failures
- Analyzing crash reports or error logs

## Debugging Methodology

### 1. Reproduce the Problem

Before anything else, get a reliable reproduction.

- Start from the exact reported conditions
- Reduce to the **minimal** reproducible case
- Automate the reproduction if possible (test case, script)
- If you can't reproduce it, gather more data (logs, state, environment)

**Key questions:**
- What exactly happens vs. what was expected?
- Does it happen every time or intermittently?
- What changed recently (deployments, config, data)?

### 2. Formulate a Hypothesis

Based on symptoms, form a specific hypothesis:

```
"The timeout occurs because the database connection pool
 is exhausted under concurrent load from the new endpoint."
```

Not: "Something is slow."

### 3. Binary Search / Bisection

The most powerful debugging technique — narrow the problem space by half each step:

- **Code bisection**: Use `git bisect` to find the commit that introduced the bug
- **Data bisection**: Test with half the dataset to find the problematic record
- **Logic bisection**: Add logging at the midpoint of the code path
- **Time bisection**: Narrow the time window of when the issue started

### 4. Verify the Fix

- The original reproduction case passes
- Related functionality is not broken (run full test suite)
- Edge cases are covered with new tests
- The fix is documented (commit message, PR description)

## Debugging Techniques by Language

### Python

```python
# 1. Use the debugger, not print statements
import pdb; pdb.set_trace()          # Basic
breakpoint()                         # Python 3.7+

# 2. Rich traceback inspection
# Install: pip install rich
from rich.traceback import install
install()

# 3. Logging with context
import logging
logging.basicConfig(level=logging.DEBUG,
    format='%(asctime)s %(name)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)
logger.debug("Processing item %s with config %s", item_id, config)

# 4. Profiling performance
import cProfile
cProfile.run('my_function()')

# Line-by-line profiling
from line_profiler import profile
@profile
def slow_function():
    ...
```

### Elixir / Erlang

```elixir
# 1. IO.inspect with labels
data
|> IO.inspect(label: "after_transform")

# 2. dbg/2 for tracing (Elixir 1.14+)
dbg(data, opts: [print_location: true])

# 3. :observer for live system inspection
:observer.start()

# 4. Process debugging
Process.info(pid, :message_queue_len)
Process.info(pid, :status)

# 5. IEx pry for interactive debugging
require IEx; IEx.pry()
# Then run: iex -S mix
# In the suspended process, you get an interactive shell
```

### JavaScript / TypeScript

```javascript
// 1. Use debugger statement (works in Node and browsers)
function processItem(item) {
  debugger;  // Execution pauses here
  return transform(item);
}

// 2. Node.js inspect flag
// node --inspect-brk my_script.js
// Then open chrome://inspect

// 3. Console methods beyond console.log
console.table(arrayOfObjects);   // Tabular display
console.trace('where am I');     // Stack trace
console.time('operation');
// ... code ...
console.timeEnd('operation');    // Elapsed time
console.groupCollapsed('details');
console.log('nested content');
console.groupEnd();
```

## Common Debugging Patterns

### The "It Works On My Machine" Problem

1. Compare environments (OS, runtime versions, dependencies)
2. Check environment variables and config files
3. Look for file path differences (case sensitivity on macOS vs Linux)
4. Verify network access and DNS resolution
5. Check locale and timezone settings

### The Intermittent Bug

1. Look for race conditions (shared mutable state, concurrent access)
2. Check for time-dependent logic (`DateTime.now()`, random seeds)
3. Examine resource exhaustion (memory, connections, file handles)
4. Add strategic logging to capture state when it fails
5. Write a stress test to reproduce the race

### The Performance Bug

```
1. Measure first (don't guess)
   - Profile CPU usage
   - Profile memory allocation
   - Profile I/O (network, disk, database)
2. Identify the bottleneck (Amdahl's Law)
3. Optimize the bottleneck
4. Re-measure to confirm improvement
```

### The Null/Nil Pointer Bug

1. Trace where the value should have been set
2. Check if initialization is conditional or deferred
3. Look for silent failures (swallowed exceptions, `rescue nil`)
4. Add explicit nil checks at boundaries
5. Consider using Option/Maybe type or result tuples

## Error Triage Checklist

When an error report comes in:

- [ ] What is the **exact** error message and stack trace?
- [ ] What is the **impact** (how many users, what functionality)?
- [ ] Can it be **reproduced** reliably?
- [ ] When did it **start** (correlate with deployments)?
- [ ] What is the **scope** (one user, all users, one region)?
- [ ] Are there **recent changes** that could be related?
- [ ] Is there **enough logging** to diagnose from prod data?

## Logging Best Practices for Debuggability

```python
# Good: Structured, searchable logs
logger.info("order_placed",
    extra={
        "order_id": order.id,
        "user_id": user.id,
        "total": order.total,
        "item_count": len(order.items),
    })

# Bad: Unstructured, hard to search
logger.info(f"Order placed for {user.name}: {order.id} total={order.total}")
```

**Rules:**
- Log at the **boundary** of every external service call (request + response)
- Include **correlation IDs** to trace requests across services
- Log **start** and **end** of operations with timing
- Use **structured logging** (JSON) in production
- Never log secrets, tokens, or PII

## Post-Mortem Template

After fixing a significant bug, document:

```markdown
## Incident: [Title]

**Duration:** Start time → End time
**Impact:** What broke, for whom, for how long
**Root Cause:** The specific technical cause
**Timeline:** Key events during investigation
**Fix:** What was changed to resolve it
**Prevention:** What to add to prevent recurrence
  - Monitoring/alerting
  - Test coverage
  - Code review checklist items
  - Architecture changes
```
