---
name: code-review
description: Comprehensive code review guidelines for quality, security, and maintainability
version: 1.0.0
author: Mana Team
tags: code-review, quality, security, best-practices
---

# Code Review Skill

Expert guidance for conducting thorough, constructive code reviews.

## When to Use

Activate this skill when:
- Reviewing pull requests or code changes
- Providing feedback on implementation approaches
- Checking for security vulnerabilities
- Ensuring code quality standards
- Mentoring team members through review

## Review Framework

### 1. First Pass - Overview

- Understand the purpose of the change
- Check PR description and linked issues
- Verify tests are included and passing
- Assess overall architecture and approach

### 2. Second Pass - Detailed Review

#### Code Quality
- [ ] Code is readable and well-organized
- [ ] Naming is clear and consistent
- [ ] Functions are focused and appropriately sized
- [ ] No obvious duplication (DRY principle)
- [ ] Comments explain "why", not "what"

#### Correctness
- [ ] Logic appears correct for the stated purpose
- [ ] Edge cases are handled
- [ ] Error handling is appropriate
- [ ] No race conditions or concurrency issues
- [ ] Resource cleanup is proper

#### Testing
- [ ] Tests cover the new/changed functionality
- [ ] Edge cases are tested
- [ ] Error paths are tested
- [ ] Test names are descriptive
- [ ] Mocking is appropriate

#### Security
- [ ] No SQL injection vulnerabilities
- [ ] Input validation is present
- [ ] No hardcoded secrets or credentials
- [ ] Authorization checks are correct
- [ ] No unsafe deserialization

#### Performance
- [ ] No obvious performance regressions
- [ ] Database queries are efficient
- [ ] No N+1 query problems
- [ ] Memory usage is reasonable
- [ ] Caching is used appropriately

### 3. Third Pass - Polish

- [ ] Documentation is updated
- [ ] Changelog entries if applicable
- [ ] Migration scripts if needed
- [ ] API documentation if public

## Language-Specific Checklists

### Python
- Type annotations present for public APIs
- No bare `except:` clauses
- Context managers used for resources
- `is` used for None checks, `==` for values

### JavaScript/TypeScript
- Strict TypeScript types where applicable
- Proper async/await error handling
- No `any` types without justification
- Memory leaks checked in callbacks

### Elixir
- Pattern matching used effectively
- Proper supervision strategies
- No Process dictionaries misuse
- OTP principles followed

### Rust
- Ownership and borrowing correct
- Error handling with Result/Option
- No unsafe blocks without review
- Lifetimes properly annotated

## Review Comment Guidelines

### Do
- Be specific about what to change and why
- Suggest code examples when helpful
- Acknowledge good patterns you see
- Ask questions rather than make demands
- Separate nitpicks from blocking issues

### Don't
- Use harsh or condescending language
- Block PRs on subjective style preferences
- Assume intent - ask clarifying questions
- Review when you're too rushed to be thorough

## Example Comments

**Good:**
```
Consider extracting this validation logic into a separate function. 
This would make it reusable and easier to unit test:

```python
def validate_email(email: str) -> bool:
    ...
```
```

**Better than:**
```
This is messy. Fix it.
```

## Security Red Flags

🚨 Immediately flag for security review:
- User input used in SQL/Shell commands
- Deserialization of untrusted data
- Authentication/authorization changes
- Cryptographic implementations
- File path construction from user input
