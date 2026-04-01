# Repo Compass Plugin - Design Document

**Issue:** `code_puppy-qo7r`  
**Status:** Planning  
**Priority:** P2

## Overview & Goals

Repo Compass is a lightweight project context plugin that automatically discovers and summarizes key project information, injecting it into the system prompt via the `get_model_system_prompt` hook. This gives agents immediate awareness of project structure, dependencies, and conventions without requiring manual exploration.

**Goals:**
1. Zero-config project awareness for agents
2. Fast startup with intelligent caching
3. Concise context under 500 tokens
4. Useful for both human and AI understanding

## Hook Integration

Uses the `get_model_system_prompt` hook to append project context to the system prompt.

```python
from code_puppy.callbacks import register_callback

def _get_repo_context(model_name, default_system_prompt, user_prompt):
    context = _build_context()
    if context:
        enhanced_prompt = f"{default_system_prompt}\n\n{context}"
        return {
            "instructions": enhanced_prompt,
            "user_prompt": user_prompt,
            "handled": False,  # Allow other hooks to also modify
        }
    return None

register_callback("get_model_system_prompt", _get_repo_context)
```

**Design Decision:** Return `handled=False` to allow chaining with other system prompt modifiers.

## File Discovery Strategy

**Priority-ordered scan:**
1. `README.md` - Project overview
2. `pyproject.toml` - Python project metadata
3. `package.json` - Node.js projects
4. `CONTRIBUTING.md` - Development guidelines
5. `CODE_OF_CONDUCT.md` - Community standards
6. `.gitignore` - Technology hints
7. `docs/` folder - Documentation structure
8. `Makefile` / `justfile` - Build commands
9. `Dockerfile` / `docker-compose.yml` - Containerization

**Discovery Algorithm:**
```python
IMPORTANT_FILES = [
    "README.md",
    "pyproject.toml",
    "package.json",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    ".gitignore",
]
DOCS_PATTERNS = ["docs/", "doc/", "documentation/"]
BUILD_FILES = ["Makefile", "justfile", "Dockerfile"]

def _discover_files(root: Path) -> dict:
    """Find and categorize important project files."""
    found = {}
    for pattern in IMPORTANT_FILES + BUILD_FILES:
        path = root / pattern
        if path.exists():
            found[pattern] = _extract_metadata(path)
    # Scan for docs folders
    for docs in DOCS_PATTERNS:
        path = root / docs
        if path.exists() and path.is_dir():
            found["docs"] = _summarize_docs(path)
            break
    return found
```

## Context Format/Template

**Structured Markdown Block:**

```markdown
## 📁 Project Context

**Name:** {project_name}  
**Type:** {project_type} | **Version:** {version}

**Description:** {brief_description}

**Tech Stack:** {detected_languages}

**Key Commands:**
- Build: {build_cmd}
- Test: {test_cmd}
- Lint: {lint_cmd}

**Structure:**
- Source: {src_dirs}
- Tests: {test_dirs}
- Docs: {docs_summary}
```

**Token Budget:** Target <500 tokens. Truncate long descriptions, limit file lists to top 5 items per category.

**Extraction Rules:**

| File | Fields Extracted |
|------|-----------------|
| `README.md` | First paragraph as description |
| `pyproject.toml` | name, version, description, dependencies (top 10) |
| `package.json` | name, version, description, scripts (key names only) |
| `.gitignore` | Top patterns indicating tech (node_modules → JS, __pycache__ → Python) |

## Caching Strategy

**Cache Location:** `.code_puppy/repo_compass_cache.json`

**Cache Schema:**
```json
{
    "generated_at": "2026-04-01T12:00:00Z",
    "file_hashes": {
        "README.md": "sha256:abc123...",
        "pyproject.toml": "sha256:def456..."
    },
    "context": "markdown content here"
}
```

**Invalidation Logic:**
```python
def _cache_valid(cache: dict, root: Path) -> bool:
    """Check if cache is still valid by comparing file hashes."""
    for file_path, old_hash in cache["file_hashes"].items():
        current_hash = _file_hash(root / file_path)
        if current_hash != old_hash:
            return False
    return True
```

**Optimization:** Use `mtime` for quick check, fall back to hash only if mtime changed.

## Configuration Schema

**`config.py`:**
```python
from dataclasses import dataclass
from typing import List, Optional

@dataclass
class RepoCompassConfig:
    enabled: bool = True
    cache_ttl_seconds: int = 300  # 5 minutes
    max_description_length: int = 200
    max_dependencies_shown: int = 10
    max_docs_files_shown: int = 5
    custom_files: List[str] = None  # Additional files to scan
    
    @classmethod
    def from_code_puppy_config(cls) -> "RepoCompassConfig":
        # Load from ~/.code_puppy/config.yaml
        pass
```

**User Config (`~/.code_puppy/config.yaml`):**
```yaml
repo_compass:
  enabled: true
  max_description_length: 300
  custom_files:
    - "ARCHITECTURE.md"
    - "DEPLOYMENT.md"
```

## File Structure

```
code_puppy/plugins/repo_compass/
├── __init__.py           # Package marker
├── register_callbacks.py # Hook registrations
├── config.py             # Configuration classes
├── discovery.py          # File discovery logic
├── extractors.py         # Per-file-type extractors
├── formatter.py          # Context formatting
├── cache.py              # Caching utilities
└── DESIGN.md             # This document
```

## Testing Approach

**Unit Tests:**
1. Mock filesystem with sample project files
2. Test each extractor independently
3. Verify cache invalidation logic
4. Test token budget enforcement

**Integration Tests:**
1. Test with real Python/Node projects
2. Verify hook integration doesn't break system prompts
3. Test performance on large monorepos

**Test Fixtures:**
- `tests/fixtures/python_project/` - Typical Python package
- `tests/fixtures/node_project/` - Node.js project
- `tests/fixtures/monorepo/` - Complex nested structure

## Implementation Phases

**Phase 1: Core Discovery (MVP)**
- Implement file discovery for top 5 file types
- Basic context formatter
- Simple in-memory cache

**Phase 2: Caching & Config**
- File-based cache with hash invalidation
- User configuration support
- Performance optimization

**Phase 3: Advanced Features**
- More file types (Docker, CI configs)
- Tech stack detection from imports
- Monorepo support with multiple contexts

## Open Questions

1. Should we cache per-project or globally?
2. How to handle very large monorepos (selective scanning)?
3. Should we include git statistics (recent activity)?
4. How to handle confidential info in scanned files?
