---
name: documentation
description: Writing clear, maintainable documentation for code, APIs, and projects
version: 1.0.0
author: Mana Team
tags: documentation, writing, api-docs, readability, onboarding
---

# Documentation Skill

Expert guidance for writing documentation that developers actually read and maintain.

## When to Use

Activate this skill when:
- Writing or updating code documentation
- Creating API documentation
- Writing README files
- Documenting architecture decisions
- Creating onboarding guides
- Writing inline code comments
- Generating documentation from code

## The Documentation Spectrum

```
Brief          ← What to aim for first
Detailed       ← Add when needed
Comprehensive  ← For public APIs and critical paths
Exhaustive     ← Almost never the right answer
```

**Rule:** Documentation should reduce time-to-understanding, not increase it.

## Layer 1: Code-Level Documentation

### Module Documentation

```python
"""Process incoming webhook events from third-party services.

This module handles the lifecycle of webhook processing:
1. Signature verification (HMAC-SHA256)
2. Payload parsing and validation
3. Event dispatching to registered handlers
4. Retry scheduling for failed deliveries

Example:
    >>> from webhooks import WebhookProcessor
    >>> processor = WebhookProcessor(secret="whsec_abc123")
    >>> result = processor.process(request.body, request.headers)
    >>> result.status
    'delivered'
"""
```

```elixir
@moduledoc """
Process incoming webhook events from third-party services.

Handles the full lifecycle: verification → parsing → dispatch → retry.

## Usage

    {:ok, result} = WebhookProcessor.process(payload, headers)
    result.status
    #=> "delivered"

## Retry Strategy

Failed deliveries are retried with exponential backoff:
1min → 5min → 30min → 2h → 12h (then dead-letter)
"""
```

### Function Documentation

Follow the **What → Why → How → Edge Cases** pattern:

```python
def reconcile_transactions(
    transactions: list[Transaction],
    bank_statements: list[BankEntry],
    tolerance_cents: int = 50,
) -> ReconciliationResult:
    """Match transactions against bank statement entries.

    Uses fuzzy amount matching (within tolerance) and date proximity
    to pair transactions with bank entries. Unmatched items on either
    side are flagged for manual review.

    Why not exact matching?
        Bank fees and currency conversion often cause small discrepancies.
        Exact matching would produce too many false negatives.

    Args:
        transactions: Internal transaction records to reconcile.
        bank_statements: Bank statement entries to match against.
        tolerance_cents: Maximum amount difference in cents to consider
            a match. Defaults to $0.50.

    Returns:
        ReconciliationResult containing matched pairs and unmatched items.

    Raises:
        ValueError: If tolerance_cents is negative.

    Example:
        >>> result = reconcile_transactions(transactions, statements)
        >>> len(result.unmatched_transactions)
        0
    """
```

### When to Comment

**Comment the "why", not the "what":**

```python
# BAD: The code already says this
x += 1  # Increment x by 1

# GOOD: Explains reasoning not obvious from code
x += 1  # API uses 1-based indexing (legacy from COBOL migration)

# GOOD: Links to external context
# See RFC-8421 §3.2 for the derivation of this formula
adjusted_rate = base_rate * (1 - loyalty_discount) * seasonal_multiplier

# GOOD: Warns about non-obvious behavior
# WARNING: This mutates the input list in place for performance.
# The caller should not reuse `items` after calling this function.
def deduplicate_sorted(items: list[str]) -> list[str]:
```

## Layer 2: API Documentation

### REST API Documentation

Every endpoint needs:

```markdown
### POST /api/v2/orders

Create a new order from the given items.

**Request Body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| items | array | yes | List of `{product_id, quantity}` objects |
| shipping_address | object | yes | Destination address |
| priority | string | no | "standard" (default) or "express" |

**Response (201):**
```json
{
  "order_id": "ord_abc123",
  "status": "confirmed",
  "total_cents": 4999,
  "estimated_delivery": "2025-01-15"
}
```

**Errors:**
| Status | Code | When |
|--------|------|------|
| 400 | INVALID_ITEMS | Empty items list or invalid product_id |
| 401 | UNAUTHORIZED | Missing or invalid auth token |
| 409 | OUT_OF_STOCK | One or more items unavailable |
| 422 | VALIDATION_ERROR | Malformed request body |
```

### Elixir Behaviour / Callback Docs

```elixir
@doc """
Store a value with the given key.

Implementations must handle concurrent writes safely. If the key
already exists, the value is overwritten.

## Example

    {:ok, _} = MyStore.put("user:123", %{name: "Alice"})

## Callback Implementation Notes

- Return `{:ok, term}` on success
- Return `{:error, reason}` on failure
- Must not raise on write failures
"""
@callback put(key :: String.t(), value :: term()) ::
            {:ok, term()} | {:error, term()}
```

## Layer 3: README.md Structure

A good README answers these questions **in order**:

```markdown
# Project Name

> One-line description of what this project does.

## Quick Start

# The FASTEST path from zero to running. Skip theory.
pip install myproject
myproject run --example

## What It Does

2-3 paragraphs explaining the problem it solves and how.

## Installation

Prerequisites, install commands, first-time setup.

## Usage

Common use cases with code examples. Start simple, add complexity.

## Configuration

All configurable options with defaults and explanations.

## Architecture

High-level design for contributors. Not needed for users.

## Contributing

How to set up dev environment, run tests, submit PRs.

## License

SPDX identifier (e.g., MIT, Apache-2.0).
```

## Layer 4: Architecture Decision Records (ADRs)

When making significant technical decisions, document them:

```markdown
# ADR-001: Use Event Sourcing for Order Management

## Status: Accepted

## Context

The order system needs a complete audit trail and the ability
to replay events for debugging. The current CRUD approach loses
intermediate state.

## Decision

We will use event sourcing for the Order aggregate. Each state
change emits an event that is persisted before being applied.

## Consequences

**Positive:**
- Complete audit trail for every order
- Ability to rebuild state from events
- Natural fit for the reporting pipeline

**Negative:**
- Higher storage requirements
- Learning curve for developers new to event sourcing
- Need to handle event schema evolution
```

## Documentation Anti-Patterns

### ❌ Don't: Document Obvious Things
```python
# BAD
def get_name(self):
    """Returns the name."""  # The function name already says this
    return self.name
```

### ❌ Don't: Let Docs Rot
- If code changes, update the doc
- If you can't keep it current, remove it (stale docs are worse than none)
- Use doctests — they fail the test suite when they get stale

### ❌ Don't: Write Novels
- A function doc should be 1-5 lines for most functions
- If you need more, the function might be doing too much
- Link to external docs for complex topics rather than inlining

### ✅ Do: Use Executable Examples
```python
def capitalize_name(name: str) -> str:
    """Capitalize a full name respecting particles (de, van, etc.).

    >>> capitalize_name("alice van der berg")
    'Alice van der Berg'
    >>> capitalize_name("JEAN-LUC PICARD")
    'Jean-Luc Picard'
    """
```

```elixir
@doc """
Capitalize a full name respecting particles (de, van, etc.).

## Examples

    iex> capitalize_name("alice van der berg")
    "Alice van der Berg"

    iex> capitalize_name("JEAN-LUC PICARD")
    "Jean-Luc Picard"
"""
```

## Documentation Maintenance Checklist

- [ ] README reflects current installation steps
- [ ] Public API functions have `@doc` / docstrings
- [ ] Docstrings include examples (doctests where possible)
- [ ] ADRs exist for major architectural decisions
- [ ] CHANGELOG is updated with each release
- [ ] No stale or commented-out documentation
- [ ] Configuration options are documented with defaults
