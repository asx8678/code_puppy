---
name: refactoring
description: Safe, incremental code refactoring techniques for improving design without changing behavior
version: 1.0.0
author: Mana Team
tags: refactoring, clean-code, design-patterns, maintainability, technical-debt
---

# Refactoring Skill

Expert guidance for safely improving code structure without changing behavior.

## When to Use

Activate this skill when:
- Reducing technical debt in existing code
- Improving code readability or maintainability
- Preparing code for new features (make the change easy, then make the easy change)
- Simplifying overly complex functions or modules
- Eliminating duplication
- Improving test coverage before refactoring

## The Prime Directive

> **Refactoring changes internal structure without changing external behavior.**
> If behavior changes, it's a rewrite — not a refactoring.

This means:
- Existing tests must continue to pass after each refactoring step
- Public APIs must remain compatible
- Each step should be small enough to verify in isolation

## The Refactoring Workflow

### Step 1: Ensure You Have a Safety Net

Before refactoring anything:

```
1. Are there tests? → If not, WRITE TESTS FIRST
2. Do the tests pass? → If not, fix existing tests first
3. Do the tests cover the code you're changing? → If not, add coverage
```

**Never refactor without tests.** Characterization tests (tests that capture current behavior, even if buggy) are acceptable as a starting point.

### Step 2: Identify the Smell

Common code smells and their refactoring:

| Smell | Refactoring |
|-------|-------------|
| Long method | Extract Function, Decompose Conditional |
| Duplicated code | Extract Function, Pull Up / Push Down Method |
| Long parameter list | Introduce Parameter Object, Preserve Whole Object |
| Divergent change | Extract Class, Extract Module |
| Shotgun surgery | Move Method, Inline Class |
| Feature envy | Move Method, Extract Method |
| Data clumps | Extract Class, Introduce Parameter Object |
| Primitive obsession | Replace Primitive with Object |
| Switch statements | Replace Conditional with Polymorphism |
| Speculative generality | Remove Dead Code, Inline Function |
| Temporary field | Extract Class |
| Message chains | Hide Delegate |
| Middle man | Remove Middle Man, Inline Delegate |
| Comments | Extract Function (make the code explain itself) |

### Step 3: Apply One Refactoring at a Time

Each step should be:
1. **Small** — a single mechanical transformation
2. **Verified** — run tests after each step
3. **Committed** — commit after each verified step

```bash
# Good refactoring commit history
git log --oneline
abc1234 Extract validate_email() from process_user()
def5678 Move validation logic to UserValidator module
ghi9012 Replace if/else chain with strategy pattern
jkl3456 Remove unused UserValidator.test_email() method
```

## Core Refactoring Techniques

### Extract Function

**When:** A code block does something identifiable, or you need a comment to explain it.

```python
# Before: What does this block do?
def process_order(order):
    # Apply discounts
    if order.customer.is_premium:
        order.total *= 0.85
    elif order.customer.years_active > 5:
        order.total *= 0.90
    elif order.item_count > 10:
        order.total *= 0.95

    # ... rest of processing ...

# After: The function name replaces the comment
def process_order(order):
    order = apply_discounts(order)
    # ... rest of processing ...

def apply_discounts(order):
    if order.customer.is_premium:
        order.total *= 0.85
    elif order.customer.years_active > 5:
        order.total *= 0.90
    elif order.item_count > 10:
        order.total *= 0.95
    return order
```

### Rename (The Most Underrated Refactoring)

**When:** Names don't clearly convey intent.

```python
# Bad: Cryptic abbreviations
def calc(d, t):
    return d * (1 + t/100)

# Good: Reveals intent
def calculate_total_with_tax(subtotal: float, tax_rate_percent: float) -> float:
    return subtotal * (1 + tax_rate_percent / 100)
```

**Naming patterns:**
- Functions: verb + noun (`get_user`, `calculate_total`, `validate_input`)
- Booleans: is/has/can/should (`is_active`, `has_permission`, `can_retry`)
- Collections: plural (`users`, `active_orders`, `pending_items`)
- Numbers: with units (`timeout_ms`, `max_retries`, `price_cents`)

### Replace Conditional with Polymorphism

**When:** A switch or if/elif chain checks the same condition in multiple places.

```python
# Before: Scattered type checks
class Order:
    def calculate_shipping(self):
        if self.type == "standard":
            return self.weight * 0.50
        elif self.type == "express":
            return self.weight * 1.50 + 10
        elif self.type == "overnight":
            return self.weight * 3.00 + 25

    def get_delivery_days(self):
        if self.type == "standard":
            return 5
        elif self.type == "express":
            return 2
        elif self.type == "overnight":
            return 1

# After: Each type encapsulates its own behavior
class Order:
    def __init__(self, shipping_strategy):
        self._strategy = shipping_strategy

    def calculate_shipping(self):
        return self._strategy.calculate_cost(self.weight)

    def get_delivery_days(self):
        return self._strategy.delivery_days

class StandardShipping:
    delivery_days = 5
    def calculate_cost(self, weight):
        return weight * 0.50

class ExpressShipping:
    delivery_days = 2
    def calculate_cost(self, weight):
        return weight * 1.50 + 10

class OvernightShipping:
    delivery_days = 1
    def calculate_cost(self, weight):
        return weight * 3.00 + 25
```

### Replace Magic Values with Named Constants

```python
# Bad: What does 86400 mean?
if time_since_last_login > 86400:
    send_reengagement_email(user)

# Good: Self-documenting
SECONDS_PER_DAY = 86_400
REENGAGEMENT_THRESHOLD_DAYS = 1

if time_since_last_login > SECONDS_PER_DAY * REENGAGEMENT_THRESHOLD_DAYS:
    send_reengagement_email(user)
```

### Introduce Parameter Object

**When:** Multiple functions take the same group of parameters.

```python
# Before: Repeated parameter clump
def create_user(name, email, role, department, manager):
    ...

def update_user(user_id, name, email, role, department, manager):
    ...

def transfer_user(user_id, new_department, new_manager):
    ...

# After: Group related data
@dataclass
class UserData:
    name: str
    email: str
    role: str
    department: str
    manager: str | None

def create_user(data: UserData) -> User:
    ...

def update_user(user_id: int, data: UserData) -> User:
    ...
```

## Refactoring in Elixir

### Pattern: Extract Named Functions from Pipelines

```elixir
# Before: Long pipeline, hard to follow
def process_order(order) do
  order
  |> Map.update!(:items, fn items ->
    Enum.map(items, fn item ->
      %{item | price: item.price * item.quantity}
    end)
  end)
  |> Map.update!(:total, fn _ ->
    Enum.sum(Enum.map(order.items, fn i -> i.price * i.quantity end))
  end)
  |> Map.put(:tax, order.total * 0.08)
  |> Map.update!(:total, &(&1 + order.tax))
end

# After: Each step has a name that explains intent
def process_order(order) do
  order
  |> calculate_line_item_totals()
  |> sum_subtotal()
  |> apply_tax()
end

defp calculate_line_item_totals(order) do
  update_in(order[:items], fn items ->
    Enum.map(items, &calculate_item_total/1)
  end)
end

defp calculate_item_total(item), do: %{item | total: item.price * item.quantity}

defp sum_subtotal(order), do: put_in(order[:subtotal], sum_items(order.items))

defp apply_tax(order), do: put_in(order[:total], order.subtotal * 1.08)
```

### Pattern: Replace nested case with `with`

```elixir
# Before: Deeply nested, hard to read
def handle_request(conn) do
  case authenticate(conn) do
    {:ok, user} ->
      case authorize(user, conn.params) do
        {:ok, :allowed} ->
          case process(conn.params) do
            {:ok, result} -> json(conn, 200, result)
            {:error, reason} -> json(conn, 422, %{error: reason})
          end
        {:error, :denied} -> json(conn, 403, %{error: "forbidden"})
      end
    {:error, :unauthenticated} -> json(conn, 401, %{error: "unauthorized"})
  end
end

# After: Flat, linear, happy path
def handle_request(conn) do
  with {:ok, user} <- authenticate(conn),
       {:ok, :allowed} <- authorize(user, conn.params),
       {:ok, result} <- process(conn.params) do
    json(conn, 200, result)
  else
    {:error, :unauthenticated} -> json(conn, 401, %{error: "unauthorized"})
    {:error, :denied} -> json(conn, 403, %{error: "forbidden"})
    {:error, reason} -> json(conn, 422, %{error: reason})
  end
end
```

## Refactoring Safety Checklist

Before starting a refactoring session:

- [ ] **Tests exist** and pass for the code to be refactored
- [ ] **Branch created** from clean main
- [ ] **Scope defined** — what's in scope and what's not
- [ ] **Small steps** — each step is one atomic refactoring
- [ ] **Run tests** after every single step
- [ ] **Commit often** — one commit per verified step
- [ ] **No feature mixing** — don't add features while refactoring
- [ ] **No behavior change** — same inputs → same outputs

## When NOT to Refactor

- The code is about to be replaced entirely (rewrite instead)
- You're too close to a deadline (add tests, document the debt, schedule later)
- You can't verify behavior (no tests and too risky to add them)
- The refactoring is larger than the feature it enables (simpler approach exists)
