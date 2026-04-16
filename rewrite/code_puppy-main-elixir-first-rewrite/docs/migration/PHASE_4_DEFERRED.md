# Phase 4 Deferred Components

This document explains why `RunLimiter`, `AdaptiveRateLimiter`, and `AgentManager` are deferred to Phase 4 of the Rust migration.

## Why Defer?

These three singletons have **113 internal references** throughout the codebase. Moving them independently would create a complex coordination nightmare and likely introduce race conditions during the transition.

More importantly, they are **tightly coupled to the agent runtime**:
- They control Python-side concurrency and agent lifecycle
- They need the agent runtime to be in Rust before they can function properly there
- Migrating them separately would require temporary Python/Rust hybrid state that's error-prone

## Dependencies on Phase 3 Bridges

Before these can migrate, we need:

| Bridge | Why It's Required |
|--------|-------------------|
| `MessageBus` | RunLimiter and AgentManager both need to broadcast state changes |
| `MCP` (Model Context Protocol) | AdaptiveRateLimiter needs cross-process model state visibility |

## Component Descriptions

### RunLimiter
- **Purpose**: Semaphore-based concurrency limiting for agent runs
- **Current State**: Python `asyncio.Semaphore` with custom queue logic
- **Phase 4 Plan**: Reimplement in Rust with async-compatible primitives

### AdaptiveRateLimiter
- **Purpose**: Circuit breaker pattern for API rate limiting per model
- **Current State**: Python `ModelRateLimitState` with backoff logic
- **Phase 4 Plan**: Rust state machine with shared cross-process visibility

### AgentManager
- **Purpose**: Agent lifecycle management and registry
- **Current State**: Python singleton with dict-based agent registry
- **Phase 4 Plan**: Rust registry with proper async lifecycle hooks

## Expected Phase 4 Approach

1. **Migrate the agent runtime first** (Phase 4 main work)
2. **Port RunLimiter** → uses same async runtime
3. **Port AdaptiveRateLimiter** → shares rate limit state across processes
4. **Port AgentManager** → final piece, orchestrates the others

This sequence avoids the messy intermediate state where some concurrency control is in Python and some in Rust.

## References

- RunLimiter: `code_puppy/run_limiter.py`
- AdaptiveRateLimiter: `code_puppy/adaptive_rate_limiter.py`
- AgentManager: `code_puppy/agent_manager.py`
