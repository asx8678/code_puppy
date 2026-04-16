"""Tech stack detection from project configuration files.

Pure filesystem scan with zero external dependencies.
"""

from __future__ import annotations

import json
import logging
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TechStackItem:
    """A detected technology in the project stack.

    Attributes:
        name: Technology name (e.g., "Python", "React", "PostgreSQL")
        version: Version string if detected, None otherwise
        category: One of "language", "framework", "database", "infra"
    """

    name: str
    version: str | None
    category: str  # "language" | "framework" | "database" | "infra"


# Framework detection patterns for package.json dependencies
_JS_FRAMEWORKS = {
    "react": "React",
    "react-dom": "React",
    "vue": "Vue",
    "vue-router": "Vue",
    "next": "Next.js",
    "nuxt": "Nuxt",
    "express": "Express",
    "fastify": "Fastify",
    "koa": "Koa",
    "nestjs": "NestJS",
    "astro": "Astro",
    "svelte": "Svelte",
    "angular": "Angular",
    "@angular/core": "Angular",
    "remix": "Remix",
    "gatsby": "Gatsby",
    "electron": "Electron",
    "react-native": "React Native",
    "expo": "Expo",
    "tailwindcss": "Tailwind CSS",
    "@mui/material": "Material UI",
    "@radix-ui": "Radix UI",
    "shadcn": "shadcn/ui",
}

# Database detection patterns
_DATABASES = {
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "mysql": "MySQL",
    "sqlite": "SQLite",
    "mongodb": "MongoDB",
    "mongoose": "MongoDB",
    "redis": "Redis",
    "elasticsearch": "Elasticsearch",
    "cassandra": "Cassandra",
    "dynamodb": "DynamoDB",
    "firebase": "Firebase",
    "supabase": "Supabase",
    "prisma": "Prisma",
    "sqlalchemy": "SQLAlchemy",
    "psycopg": "PostgreSQL",
    "pymongo": "MongoDB",
    "aioredis": "Redis",
}

# Build tool detection patterns
_BUILD_TOOLS = {
    "webpack": "Webpack",
    "vite": "Vite",
    "rollup": "Rollup",
    "parcel": "Parcel",
    "esbuild": "esbuild",
    "turbopack": "Turbopack",
    "turbo": "Turborepo",
}


def _safe_read_text(path: Path) -> str | None:
    """Safely read text from a file, returning None on any error."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _parse_json(path: Path) -> dict[str, Any] | None:
    """Parse JSON file, returning None on any error."""
    text = _safe_read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _extract_version(version_str: str | None) -> str | None:
    """Clean up version string (strip ^, ~, >=, etc.)."""
    if not version_str:
        return None
    # Remove common prefixes
    cleaned = re.sub(r"^[~^>=<]+", "", version_str.strip())
    # Keep only major.minor if present
    match = re.match(r"(\d+(?:\.\d+)?)", cleaned)
    return match.group(1) if match else None


def _detect_from_package_json(root: Path) -> list[TechStackItem]:
    """Detect tech stack from package.json."""
    items: list[TechStackItem] = []
    package_json = root / "package.json"
    data = _parse_json(package_json)
    if data is None:
        return items

    deps: dict[str, str] = {}
    deps.update(data.get("dependencies", {}))
    deps.update(data.get("devDependencies", {}))

    # Detect frameworks
    detected_frameworks: set[str] = set()
    for dep_name, version in deps.items():
        for pattern, framework in _JS_FRAMEWORKS.items():
            if pattern in dep_name.lower() and framework not in detected_frameworks:
                ver = _extract_version(version)
                items.append(TechStackItem(framework, ver, "framework"))
                detected_frameworks.add(framework)
                break

    # Detect databases
    detected_dbs: set[str] = set()
    for dep_name, version in deps.items():
        for pattern, db in _DATABASES.items():
            if pattern in dep_name.lower() and db not in detected_dbs:
                ver = _extract_version(version)
                items.append(TechStackItem(db, ver, "database"))
                detected_dbs.add(db)
                break

    # Detect build tools
    detected_build: set[str] = set()
    for dep_name, version in deps.items():
        for pattern, tool in _BUILD_TOOLS.items():
            if pattern in dep_name.lower() and tool not in detected_build:
                ver = _extract_version(version)
                items.append(TechStackItem(tool, ver, "infra"))
                detected_build.add(tool)
                break

    # Node version from engines
    engines = data.get("engines", {})
    if "node" in engines:
        node_ver = _extract_version(engines["node"])
        items.append(TechStackItem("Node.js", node_ver, "language"))

    return items


def _parse_pyproject_toml(path: Path) -> dict[str, Any] | None:
    """Parse pyproject.toml file, returning None on any error."""
    try:
        text = path.read_text(encoding="utf-8")
        return tomllib.loads(text)
    except (OSError, UnicodeDecodeError, ValueError, tomllib.TOMLDecodeError):
        return None


def _extract_deps_from_pyproject(data: dict[str, Any]) -> list[str]:
    """Extract all dependency names from parsed pyproject.toml data.

    Parses [project.dependencies] and [project.optional-dependencies].
    Returns a list of lowercase dependency names for case-insensitive matching.
    """
    deps: set[str] = set()

    project = data.get("project", {})
    if not isinstance(project, dict):
        return []

    # Main dependencies from [project.dependencies]
    main_deps = project.get("dependencies", [])
    if isinstance(main_deps, list):
        for dep in main_deps:
            if isinstance(dep, str):
                # Extract package name from dependency string
                # Handles formats like: "fastapi>=0.100", "pydantic[email]", "typer >= 0.24"
                dep_name = _extract_package_name(dep)
                if dep_name:
                    deps.add(dep_name.lower())

    # Optional dependencies from [project.optional-dependencies]
    optional_deps = project.get("optional-dependencies", {})
    if isinstance(optional_deps, dict):
        for group_name, group_deps in optional_deps.items():
            if isinstance(group_deps, list):
                for dep in group_deps:
                    if isinstance(dep, str):
                        dep_name = _extract_package_name(dep)
                        if dep_name:
                            deps.add(dep_name.lower())

    return list(deps)


def _extract_package_name(dep_string: str) -> str | None:
    """Extract package name from a dependency string.

    Handles various formats:
    - "fastapi>=0.100" -> "fastapi"
    - "pydantic[email]" -> "pydantic"
    - "typer >= 0.24" -> "typer"
    - "some-package_name" -> "some-package_name"
    """
    if not dep_string:
        return None

    # Strip whitespace and extract the name part (before version specifiers)
    dep = dep_string.strip()

    # Find where the package name ends (first special character)
    # Package names can contain letters, digits, hyphens, underscores, dots
    match = re.match(r'^([a-zA-Z0-9][-a-zA-Z0-9._]*)', dep)
    if match:
        return match.group(1).lower()

    return None


def _has_tool_section(data: dict[str, Any], tool_name: str) -> bool:
    """Check if a [tool.{tool_name}] section exists in pyproject.toml."""
    tool = data.get("tool", {})
    if not isinstance(tool, dict):
        return False
    return tool_name in tool


def _detect_from_pyproject_toml(root: Path) -> list[TechStackItem]:
    """Detect tech stack from pyproject.toml using proper TOML parsing."""
    items: list[TechStackItem] = []
    pyproject = root / "pyproject.toml"

    data = _parse_pyproject_toml(pyproject)
    if data is None:
        return items

    project = data.get("project", {})
    if not isinstance(project, dict):
        # Still detect Python if file exists but has no [project] section
        items.append(TechStackItem("Python", None, "language"))
    else:
        # Extract Python version from requires-python
        requires_python = project.get("requires-python")
        if requires_python:
            python_ver = _extract_version(requires_python)
            items.append(TechStackItem("Python", python_ver, "language"))
        else:
            items.append(TechStackItem("Python", None, "language"))

    # Get all dependencies for framework detection
    all_deps = _extract_deps_from_pyproject(data)
    all_deps_set = set(all_deps)  # For O(1) lookups

    # Detect frameworks from dependencies
    framework_patterns: dict[str, str] = {
        "django": "Django",
        "flask": "Flask",
        "fastapi": "FastAPI",
        "tornado": "Tornado",
        "pyramid": "Pyramid",
        "starlette": "Starlette",
        "trio": "Trio",
        "aiohttp": "AIOHTTP",
        "bottle": "Bottle",
    }

    detected: set[str] = set()
    for dep_name, framework_name in framework_patterns.items():
        if dep_name in all_deps_set and framework_name not in detected:
            items.append(TechStackItem(framework_name, None, "framework"))
            detected.add(framework_name)

    # Detect testing frameworks
    test_deps = {"pytest", "unittest", "nose", "nose2", "trial"}
    if any(dep in all_deps_set for dep in test_deps) or _has_tool_section(data, "pytest"):
        items.append(TechStackItem("pytest", None, "infra"))

    # Detect linting/formatting tools
    lint_tools = [
        ("ruff", "ruff"),
        ("black", "Black"),
        ("isort", "isort"),
        ("mypy", "mypy"),
        ("flake8", "flake8"),
        ("pylint", "Pylint"),
    ]
    for dep_name, tool_name in lint_tools:
        if dep_name in all_deps_set or _has_tool_section(data, dep_name):
            items.append(TechStackItem(tool_name, None, "infra"))
            break  # Only add first detected lint tool

    return items


def _detect_from_cargo_toml(root: Path) -> list[TechStackItem]:
    """Detect tech stack from Cargo.toml."""
    items: list[TechStackItem] = []
    cargo_toml = root / "Cargo.toml"
    text = _safe_read_text(cargo_toml)
    if text is None:
        return items

    # Extract Rust edition as version hint
    edition_match = re.search(r'edition\s*=\s*["\']([^"\']+)["\']', text)
    edition = edition_match.group(1) if edition_match else None

    items.append(TechStackItem("Rust", edition, "language"))

    # Detect popular Rust frameworks/libraries
    framework_patterns = [
        (r'tokio\s*=', "Tokio"),
        (r'axum\s*=', "Axum"),
        (r'actix-web\s*=', "Actix-web"),
        (r'rocket\s*=', "Rocket"),
        (r'warp\s*=', "Warp"),
        (r'tide\s*=', "Tide"),
        (r'serde\s*=', "serde"),
        (r'pyo3\s*=', "PyO3"),
        (r'sqlx\s*=', "SQLx"),
        (r'diesel\s*=', "Diesel"),
    ]

    detected: set[str] = set()
    for pattern, name in framework_patterns:
        if re.search(pattern, text, re.IGNORECASE) and name not in detected:
            items.append(TechStackItem(name, None, "framework"))
            detected.add(name)

    return items


def _detect_from_go_mod(root: Path) -> list[TechStackItem]:
    """Detect tech stack from go.mod."""
    items: list[TechStackItem] = []
    go_mod = root / "go.mod"
    text = _safe_read_text(go_mod)
    if text is None:
        return items

    # Extract Go version
    go_version_match = re.search(r'^go\s+(\d+\.\d+)', text, re.MULTILINE)
    go_ver = go_version_match.group(1) if go_version_match else None

    items.append(TechStackItem("Go", go_ver, "language"))

    # Detect popular Go frameworks
    framework_patterns = [
        (r'github\.com/gin-gonic', "Gin"),
        (r'github\.com/labstack/echo', "Echo"),
        (r'github\.com/gofiber/fiber', "Fiber"),
        (r'github\.com/gorilla/mux', "Gorilla Mux"),
        (r'google\.golang\.org/grpc', "gRPC"),
        (r'go\.uber\.org/zap', "Zap"),
        (r'github\.com/sirupsen/logrus', "Logrus"),
    ]

    detected: set[str] = set()
    for pattern, name in framework_patterns:
        if re.search(pattern, text, re.IGNORECASE) and name not in detected:
            items.append(TechStackItem(name, None, "framework"))
            detected.add(name)

    return items


def _detect_from_gemfile(root: Path) -> list[TechStackItem]:
    """Detect tech stack from Gemfile."""
    items: list[TechStackItem] = []
    gemfile = root / "Gemfile"
    text = _safe_read_text(gemfile)
    if text is None:
        return items

    items.append(TechStackItem("Ruby", None, "language"))

    # Detect popular Ruby frameworks/gems
    framework_patterns = [
        (r"gem\s+['\"]rails", "Rails"),
        (r"gem\s+['\"]sinatra", "Sinatra"),
        (r"gem\s+['\"]hanami", "Hanami"),
        (r"gem\s+['\"]rspec", "RSpec"),
        (r"gem\s+['\"]minitest", "Minitest"),
        (r"gem\s+['\"]pg", "PostgreSQL"),
        (r"gem\s+['\"]mysql2", "MySQL"),
        (r"gem\s+['\"]redis", "Redis"),
    ]

    detected: set[str] = set()
    for pattern, name in framework_patterns:
        if re.search(pattern, text, re.IGNORECASE) and name not in detected:
            category = "framework" if name in {"Rails", "Sinatra", "Hanami"} else "database" if name in {"PostgreSQL", "MySQL", "Redis"} else "infra"
            items.append(TechStackItem(name, None, category))
            detected.add(name)

    return items


def _detect_from_dockerfile(root: Path) -> list[TechStackItem]:
    """Detect infrastructure hints from Dockerfile/docker-compose.yml."""
    items: list[TechStackItem] = []

    dockerfile = root / "Dockerfile"
    compose = root / "docker-compose.yml"
    compose_yaml = root / "docker-compose.yaml"

    has_docker = False

    if dockerfile.exists():
        has_docker = True
        text = _safe_read_text(dockerfile)
        if text:
            # Try to detect base image language hints
            base_match = re.search(r'^FROM\s+(\S+)', text, re.MULTILINE | re.IGNORECASE)
            if base_match:
                base = base_match.group(1).lower()
                if "python" in base:
                    items.append(TechStackItem("Python", None, "language"))
                elif "node" in base or "nodejs" in base:
                    items.append(TechStackItem("Node.js", None, "language"))
                elif "ruby" in base:
                    items.append(TechStackItem("Ruby", None, "language"))
                elif "golang" in base or "go:" in base:
                    items.append(TechStackItem("Go", None, "language"))
                elif "rust" in base:
                    items.append(TechStackItem("Rust", None, "language"))

    if compose.exists() or compose_yaml.exists():
        has_docker = True
        compose_path = compose if compose.exists() else compose_yaml
        text = _safe_read_text(compose_path)
        if text:
            # Simple pattern matching for common services
            services_match = re.search(r'postgres', text, re.IGNORECASE)
            if services_match:
                items.append(TechStackItem("PostgreSQL", None, "database"))
            if re.search(r'redis', text, re.IGNORECASE):
                items.append(TechStackItem("Redis", None, "database"))
            if re.search(r'mongo', text, re.IGNORECASE):
                items.append(TechStackItem("MongoDB", None, "database"))

    if has_docker:
        items.append(TechStackItem("Docker", None, "infra"))

    return items


def _detect_from_makefile(root: Path) -> list[TechStackItem]:
    """Detect build tooling hints from Makefile."""
    items: list[TechStackItem] = []
    makefile = root / "Makefile"
    justfile = root / "justfile"

    if makefile.exists():
        items.append(TechStackItem("Make", None, "infra"))
    if justfile.exists():
        items.append(TechStackItem("Just", None, "infra"))

    return items


def detect_tech_stack(root: Path) -> list[TechStackItem]:
    """Detect the technology stack of a project by scanning config files.

    Args:
        root: Project root directory path

    Returns:
        List of TechStackItem, deduplicated and ordered by priority:
        language -> framework -> database -> infra
    """
    all_items: list[TechStackItem] = []

    # Run all detectors
    all_items.extend(_detect_from_package_json(root))
    all_items.extend(_detect_from_pyproject_toml(root))
    all_items.extend(_detect_from_cargo_toml(root))
    all_items.extend(_detect_from_go_mod(root))
    all_items.extend(_detect_from_gemfile(root))
    all_items.extend(_detect_from_dockerfile(root))
    all_items.extend(_detect_from_makefile(root))

    # Deduplicate by name, keeping first occurrence (which has version info)
    seen: set[str] = set()
    unique_items: list[TechStackItem] = []
    for item in all_items:
        if item.name not in seen:
            unique_items.append(item)
            seen.add(item.name)

    # Sort by category priority
    category_order = {"language": 0, "framework": 1, "database": 2, "infra": 3}
    unique_items.sort(key=lambda x: category_order.get(x.category, 99))

    return unique_items


def detect_build_commands(root: Path) -> dict[str, str]:
    """Detect available build/test/lint commands from project files.

    Args:
        root: Project root directory path

    Returns:
        Dict mapping command type to command string (e.g., {"test": "pytest", "lint": "ruff"})
    """
    commands: dict[str, str] = {}

    # Check package.json scripts
    package_json = root / "package.json"
    data = _parse_json(package_json)
    if data:
        scripts = data.get("scripts", {})
        script_map = {
            "test": "test",
            "build": "build",
            "lint": "lint",
            "dev": "dev",
            "start": "start",
            "format": "format",
            "typecheck": "typecheck",
        }
        for cmd_type, script_key in script_map.items():
            for key in scripts:
                if script_key in key.lower() and cmd_type not in commands:
                    commands[cmd_type] = f"npm run {key}"
                    break

    # Check pyproject.toml using proper TOML parsing
    pyproject = root / "pyproject.toml"
    pp_data = _parse_pyproject_toml(pyproject)
    if pp_data is not None:
        # Get all dependencies for detection
        all_deps_set = set(_extract_deps_from_pyproject(pp_data))

        # Detect pytest
        if "pytest" in all_deps_set or _has_tool_section(pp_data, "pytest"):
            commands.setdefault("test", "pytest")
        # Detect ruff
        if "ruff" in all_deps_set or _has_tool_section(pp_data, "ruff"):
            commands.setdefault("lint", "ruff check")
            commands.setdefault("format", "ruff format")
        # Detect mypy
        if "mypy" in all_deps_set or _has_tool_section(pp_data, "mypy"):
            commands.setdefault("typecheck", "mypy")
        # Detect build tools from dependencies
        build_tools = {"hatchling", "maturin", "setuptools", "poetry", "flit", "hatch"}
        if any(tool in all_deps_set for tool in build_tools):
            commands.setdefault("build", "pip build")

    # Check Makefile
    makefile = root / "Makefile"
    text = _safe_read_text(makefile)
    if text:
        target_patterns = [
            (r"^test:?", "test", "make test"),
            (r"^build:?", "build", "make build"),
            (r"^lint:?", "lint", "make lint"),
            (r"^dev:?", "dev", "make dev"),
            (r"^format:?", "format", "make format"),
            (r"^check:?", "typecheck", "make check"),
        ]
        for pattern, cmd_type, cmd_value in target_patterns:
            if re.search(pattern, text, re.MULTILINE | re.IGNORECASE):
                commands.setdefault(cmd_type, cmd_value)

    # Check justfile
    justfile = root / "justfile"
    text = _safe_read_text(justfile)
    if text:
        recipe_patterns = [
            (r"^test", "test", "just test"),
            (r"^build", "build", "just build"),
            (r"^lint", "lint", "just lint"),
            (r"^dev", "dev", "just dev"),
            (r"^format", "format", "just format"),
        ]
        for pattern, cmd_type, cmd_value in recipe_patterns:
            if re.search(pattern, text, re.MULTILINE | re.IGNORECASE):
                commands.setdefault(cmd_type, cmd_value)

    return commands
