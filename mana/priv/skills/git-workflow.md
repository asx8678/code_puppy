---
name: git-workflow
description: Git best practices for branching, commits, merging, and collaborative development
version: 1.0.0
author: Mana Team
tags: git, version-control, collaboration, workflow
---

# Git Workflow Skill

Expert guidance for effective Git usage and collaborative development.

## When to Use

Activate this skill when:
- Setting up a new repository
- Deciding on a branching strategy
- Writing commit messages
- Handling merge conflicts
- Reviewing pull/merge requests
- Troubleshooting Git issues

## Branching Strategies

### Git Flow (Traditional)

Best for: Released software with versioning

```
main/master    ─────●─────●─────●─────●─────●─────
                   /     /     /     /     /
develop     ─────●─────●─────●─────●─────●─────
                 / \
feature/xyz   ───●──●                    (merged back to develop)
                   \
release/1.0   ──────●──●──●  (branched from develop, merged to main)
```

**Branches:**
- `main` - Production-ready code
- `develop` - Integration branch for features
- `feature/*` - Individual features
- `release/*` - Release preparation
- `hotfix/*` - Emergency fixes to main

### GitHub Flow (Simple)

Best for: Continuous deployment, web applications

```
main        ─────●─────●─────●─────●─────●─────
               /     /     /     /     /
feature/a   ───●────┘     /     /     /
feature/b   ─────────────●──────┘     /
feature/c   ──────────────────────────●──
```

**Process:**
1. Create feature branch from main
2. Make commits
3. Open pull request
4. Review and discuss
5. Deploy for testing (optional)
6. Merge to main

### Trunk-Based Development

Best for: High-velocity teams, CI/CD

```
main/trunk  ─────●─●─●─●─●─●─●─●─●─●─●─●─●─●─●─
                  / /       /         /
short-lived   ───●─┘       /         /
branches    ─────────────●─────────┘
(max 1 day)
```

**Principles:**
- Short-lived branches (hours to 1 day)
- Feature flags for incomplete work
- Frequent integration to main

## Commit Best Practices

### Commit Message Format (Conventional Commits)

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Formatting, semicolons, etc.
- `refactor`: Code change that neither fixes nor adds feature
- `test`: Adding or correcting tests
- `chore`: Build, dependencies, etc.

**Examples:**

```
feat(auth): implement OAuth login flow

- Add Google OAuth provider
- Add GitHub OAuth provider
- Update user model for OAuth tokens

Closes #123
```

```
fix(api): handle null user gracefully

Return 401 instead of 500 when user is null in auth middleware.

Fixes #456
```

### Commit Guidelines

1. **Atomic commits** - One logical change per commit
2. **Separate formatting** - Don't mix formatting with logic changes
3. **Commit early, commit often** - Easier to review and revert
4. **Never commit broken code** - Tests should pass
5. **Write good messages** - Future you will thank you

## Handling Conflicts

### Prevention

1. **Pull frequently** from the base branch
2. **Communicate** with team about touched files
3. **Small PRs** - Less surface area for conflicts
4. **Feature flags** - Avoid long-running branches

### Resolution

```bash
# When merge conflict occurs
git status  # See conflicting files

# Edit files to resolve conflicts
# Look for <<<<<<< HEAD markers

# After fixing
git add <resolved-files>
git commit  # Use default merge message
```

### Using Rebase

```bash
# Update your feature branch with latest main
git checkout feature-branch
git fetch origin
git rebase origin/main

# If conflicts during rebase
git add <resolved-files>
git rebase --continue
# or git rebase --abort to cancel
```

**Rule of Thumb:**
- Use `merge` for integrating completed features (preserves history)
- Use `rebase` for cleaning up local branches before pushing
- **Never rebase pushed/shared branches**

## Pull Request Best Practices

### Creating PRs

1. **Small and focused** - Under 400 lines when possible
2. **Clear description** - What, why, and how
3. **Screenshots** - For UI changes
4. **Test instructions** - How to verify
5. **Linked issues** - Use "Closes #123" syntax

### PR Description Template

```markdown
## Summary
Brief description of changes

## Changes
- Change 1
- Change 2

## Testing
How to test these changes

## Screenshots (if applicable)

## Checklist
- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] Code follows style guide

## Related Issues
Closes #123
```

### Reviewing PRs

**As Author:**
- Respond to all comments
- Don't take feedback personally
- Explain reasoning when disagreeing
- Make requested changes promptly

**As Reviewer:**
- Review within 24 hours
- Be constructive and specific
- Approve when satisfied, don't just +1
- Test the code if it's a critical area

## Useful Git Commands

```bash
# See what changed in last commit
git show

# See commit history as graph
git log --oneline --graph --all

# Undo last commit but keep changes
git reset --soft HEAD~1

# Stash changes temporarily
git stash push -m "description"
git stash pop  # or list with git stash list

# Find which commit introduced a bug
git bisect start
git bisect bad  # current is bad
git bisect good <commit>  # known good commit

# Cherry-pick a commit from another branch
git cherry-pick <commit-hash>

# See blame for specific lines
git blame -L 10,20 <file>

# Clean up merged branches
git branch --merged | grep -v "\*" | xargs -n 1 git branch -d
```

## Repository Hygiene

### .gitignore Template

```
# Dependencies
node_modules/
vendor/
__pycache__/
*.egg-info/

# Build outputs
build/
dist/
*.exe
*.dll
*.so

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# OS files
.DS_Store
Thumbs.db

# Environment
.env
.env.local
.venv/

# Testing
.coverage
htmlcov/
.pytest_cache/

# Logs
*.log
logs/
```

### Hooks Setup

```bash
# Pre-commit hook for linting
#!/bin/sh
# .git/hooks/pre-commit

# Run linter
npm run lint
if [ $? -ne 0 ]; then
    echo "Linting failed. Commit aborted."
    exit 1
fi

# Run tests
npm test
if [ $? -ne 0 ]; then
    echo "Tests failed. Commit aborted."
    exit 1
fi
```

Use [lefthook](https://github.com/evilmartians/lefthook) or [husky](https://typicode.github.io/husky/) for easier hook management.
