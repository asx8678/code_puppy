---
name: python-development
description: Modern Python development best practices with async, type safety, and testing
version: 1.0.0
author: Mana Team
tags: python, development, typing, async, best-practices
---

# Python Development Skill

Expert guidance for writing production-quality Python code.

## When to Use

Activate this skill when:
- Writing new Python code or refactoring existing code
- Setting up Python projects with proper structure
- Implementing async/await patterns
- Adding type annotations
- Optimizing Python performance

## Core Principles

### 1. Pythonic Code

Follow the Zen of Python (PEP 20):
- Explicit is better than implicit
- Readability counts
- Simple is better than complex
- There should be one obvious way to do it

### 2. Type Safety

- Add complete type annotations for ALL public APIs
- Use mypy in strict mode
- Leverage generics with `TypeVar` and `ParamSpec`
- Use `Protocol` for structural typing
- Prefer `TypedDict` over plain dicts for structured data

```python
from typing import TypedDict, Protocol, TypeVar

T = TypeVar('T')

class Drawable(Protocol):
    def draw(self) -> None: ...

class UserData(TypedDict):
    name: str
    age: int
```

### 3. Modern Python Features (3.9+)

- Pattern matching with `match/case`
- Walrus operator `:=` for assignment expressions
- Union types with `X | Y` syntax
- Built-in generic types (list[str], dict[str, int])
- Decorators for cross-cutting concerns

### 4. Async Excellence

- Use `asyncio` for I/O-bound operations
- Never block the event loop
- Use `async with` for async context managers
- Leverage `asyncio.gather()` for concurrency
- Consider `anyio` for library compatibility

```python
async def fetch_data(urls: list[str]) -> list[bytes]:
    async with aiohttp.ClientSession() as session:
        tasks = [session.get(url) for url in urls]
        responses = await asyncio.gather(*tasks)
        return [await r.read() for r in responses]
```

### 5. Code Quality Gates

Before considering code complete:
- [ ] `ruff check .` passes (linting)
- [ ] `ruff format .` applied (formatting)
- [ ] `mypy . --strict` passes (type checking)
- [ ] `pytest --cov` passes with >90% coverage
- [ ] `bandit -r .` passes (security scan)

## Project Structure

```
project/
├── src/
│   └── project/
│       ├── __init__.py
│       └── module.py
├── tests/
│   ├── __init__.py
│   └── test_module.py
├── pyproject.toml      # Modern Python packaging
├── README.md
└── .gitignore
```

## Testing Strategy

- Use pytest as the test runner
- Write fixtures in `conftest.py`
- Use `pytest.mark.parametrize` for edge cases
- Mock external dependencies with `unittest.mock`
- Target >90% test coverage

## Performance Considerations

- Use generators for large datasets
- Leverage `functools.lru_cache` for memoization
- Profile with `cProfile` before optimizing
- Consider `numba` or `cython` for hot paths
- Use `asyncio` for I/O-bound, `multiprocessing` for CPU-bound
