from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
    "build",
    ".venv",
    "venv",
}

IMPORTANT_FILES = (
    "README.md",
    "pyproject.toml",
    "package.json",
    "Makefile",
    "justfile",
)


@dataclass(frozen=True, slots=True)
class FileSummary:
    path: str
    kind: str
    symbols: tuple[str, ...] = ()


def _is_hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts if part not in {".", ".."})


def _iter_candidate_files(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        if _is_hidden(rel):
            continue
        candidates.append(path)
    return sorted(candidates, key=lambda p: (len(p.relative_to(root).parts), str(p.relative_to(root))))


def _summarize_python_file(path: Path, root: Path, max_symbols: int) -> FileSummary | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None

    symbols: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [arg.arg for arg in node.args.args]
            signature = f"def {node.name}({', '.join(args)})"
            symbols.append(signature)
        elif isinstance(node, ast.ClassDef):
            methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            suffix = f" methods={','.join(methods[:3])}" if methods else ""
            symbols.append(f"class {node.name}{suffix}")
        if len(symbols) >= max_symbols:
            break

    return FileSummary(path=str(path.relative_to(root)), kind="python", symbols=tuple(symbols))


def _summarize_non_python_file(path: Path, root: Path) -> FileSummary | None:
    name = path.name
    rel = str(path.relative_to(root))
    if name in IMPORTANT_FILES:
        return FileSummary(path=rel, kind="project-file")
    if path.suffix in {".md", ".rst"}:
        return FileSummary(path=rel, kind="docs")
    if path.suffix in {".js", ".ts", ".tsx", ".json", ".toml", ".yaml", ".yml"}:
        return FileSummary(path=rel, kind=path.suffix.lstrip("."))
    return None


def build_structure_map(root: Path, max_files: int = 40, max_symbols_per_file: int = 8) -> list[FileSummary]:
    summaries: list[FileSummary] = []
    for path in _iter_candidate_files(root):
        summary: FileSummary | None
        if path.suffix == ".py":
            summary = _summarize_python_file(path, root, max_symbols_per_file)
        else:
            summary = _summarize_non_python_file(path, root)
        if summary is not None:
            summaries.append(summary)
        if len(summaries) >= max_files:
            break
    return summaries
