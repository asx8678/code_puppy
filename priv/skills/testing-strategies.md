---
name: testing-strategies
description: Comprehensive testing methodologies for unit, integration, and end-to-end tests
version: 1.0.0
author: Mana Team
tags: testing, tdd, pytest, quality, qa
---

# Testing Strategies Skill

Expert guidance for implementing effective test suites.

## When to Use

Activate this skill when:
- Setting up testing infrastructure for a project
- Writing unit tests for new functionality
- Creating integration tests for services
- Debugging flaky or failing tests
- Improving test coverage

## Testing Pyramid

```
       /\
      /  \      E2E Tests (few, critical paths)
     /----\     
    /      \    Integration Tests (some, key interactions)
   /--------\
  /          \  Unit Tests (many, fast, isolated)
 /------------\
```

## Unit Testing

### Principles
- Test one thing at a time
- Tests should be independent and isolated
- Fast execution (< 10ms per test ideally)
- No external dependencies (use mocks)

### Test Structure (AAA Pattern)

```python
# Arrange - Set up test data and mocks
def test_user_can_withdraw_funds():
    account = Account(balance=100)
    
    # Act - Execute the code being tested
    result = account.withdraw(50)
    
    # Assert - Verify the outcome
    assert result is True
    assert account.balance == 50
```

### Fixtures and Setup

```python
import pytest

@pytest.fixture
def database():
    db = create_test_db()
    yield db
    db.cleanup()

@pytest.fixture
def user(database):
    return User.create(db=database, name="Test User")
```

### Parametrized Tests

```python
@pytest.mark.parametrize("input,expected", [
    ("hello", 5),
    ("world", 5),
    ("", 0),
    ("a" * 1000, 1000),
])
def test_string_length(input, expected):
    assert len(input) == expected
```

## Integration Testing

### When to Use
- Testing database interactions
- Testing API endpoints
- Testing service-to-service communication
- Testing with real (but test) dependencies

### Best Practices
- Use test databases/containers
- Clean state between tests
- Test happy path and error paths
- Verify side effects (database changes, messages sent)

### Example Pattern

```python
async def test_create_user_endpoint(client, db):
    # Given
    user_data = {"name": "Alice", "email": "alice@example.com"}
    
    # When
    response = await client.post("/users", json=user_data)
    
    # Then
    assert response.status_code == 201
    assert response.json()["name"] == "Alice"
    
    # Verify side effect
    user_in_db = await db.users.find_one({"email": "alice@example.com"})
    assert user_in_db is not None
```

## Mocking and Patching

### When to Mock
- External API calls
- Database interactions (in unit tests)
- Time-dependent functions
- Random number generators
- File system operations

### Python Mocking

```python
from unittest.mock import Mock, patch, MagicMock

# Patch a function
with patch('module.external_api_call') as mock_api:
    mock_api.return_value = {"status": "ok"}
    result = process_data()
    mock_api.assert_called_once_with(expected_args)

# Mock object
mock_db = Mock()
mock_db.query.return_value = [user1, user2]
```

## Test Coverage

### Coverage Goals
- Aim for 80%+ overall coverage
- Critical paths should be 100% covered
- Don't test trivial getters/setters just for numbers
- Focus on business logic and edge cases

### Running Coverage

```bash
# Python with pytest
pytest --cov=src --cov-report=html --cov-report=term-missing

# JavaScript
npm test -- --coverage
```

## Test-Driven Development (TDD)

### The Red-Green-Refactor Cycle

1. **Red**: Write a failing test that defines the behavior you want
2. **Green**: Write the minimum code to make the test pass
3. **Refactor**: Clean up the code while keeping tests green

### Benefits
- Better design (forces thinking about API first)
- Confidence in changes
- Living documentation
- Fewer bugs

### When NOT to TDD
- Exploring unfamiliar APIs
- Prototyping/spikes
- UI-heavy features (may use outside-in testing instead)

## Test Organization

### Directory Structure

```
tests/
├── unit/                    # Pure unit tests
│   ├── test_models.py
│   └── test_services.py
├── integration/             # Integration tests
│   ├── test_database.py
│   └── test_api.py
├── e2e/                     # End-to-end tests
│   └── test_user_flows.py
├── fixtures/                # Test data
│   └── sample_data.json
└── conftest.py             # Shared fixtures
```

### Test Naming
- Descriptive: `test_user_can_withdraw_funds`
- Not: `test_withdraw` or `test_1`
- Should read like a specification

## Flaky Test Prevention

### Common Causes
- Time-dependent logic
- Random data without seeds
- Shared mutable state
- External dependencies
- Race conditions

### Solutions
- Use `freezegun` for time mocking
- Set random seeds in tests
- Clean up after each test
- Use test containers for dependencies
- Add retry logic only if absolutely necessary
