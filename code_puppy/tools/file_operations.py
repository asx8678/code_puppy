# file_operations.py

# ---------------------------------------------------------------------------
# Module-level helper functions (exposed for unit tests _and_ used as tools)
# ---------------------------------------------------------------------------
import asyncio
import atexit
import functools
import os
import shutil
import stat
import subprocess
import tempfile

from pydantic import BaseModel
from pydantic_ai import RunContext

from code_puppy.async_utils import format_size
from code_puppy.concurrency_limits import FileOpsLimiter
from code_puppy.constants import (
    MAX_GREP_FILE_SIZE_BYTES,
    MAX_GREP_MATCHES,
    MAX_READ_FILE_TOKENS,
)
from code_puppy.messaging import (  # New structured messaging types
    FileContentMessage,
    FileEntry,
    FileListingMessage,
    GrepMatch,
    GrepResultMessage,
    get_message_bus,
)
from code_puppy.token_counting import count_tokens
from code_puppy.utils.eol import normalize_eol, strip_bom

# Maximum files to collect in list_files before early exit
# This prevents memory exhaustion on huge repos
MAX_LIST_FILES_ENTRIES = 10000
from code_puppy.utils.file_display import (
    format_content_with_line_numbers,
    truncate_with_guidance,
)
from code_puppy.utils.gitignore import is_gitignored
from code_puppy.utils.install_hints import format_missing_tool_message
from code_puppy.utils.macos_path import resolve_path_with_variants


# Pydantic models for tool return types
class ListedFile(BaseModel):
    path: str | None
    type: str | None
    size: int = 0
    full_path: str | None
    depth: int | None


# Cached ignore file creation - deterministic patterns, avoid 213 tempfile writes per call
@functools.lru_cache(maxsize=1)
def _get_grep_ignore_file() -> str:
    """Create a temporary ignore file with DIR_IGNORE_PATTERNS.

    Cached to avoid recreating the same file on every grep/list_files call.
    Returns the path to the temporary file.
    """
    from code_puppy.tools.common import DIR_IGNORE_PATTERNS

    f = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".ignore")
    ignore_file = f.name
    # Batch write all patterns at once with newline.join for efficiency
    filtered = [p for p in DIR_IGNORE_PATTERNS]
    f.write("\n".join(filtered))
    f.close()
    return ignore_file


# Register cleanup at exit
@atexit.register
def _cleanup_ignore_file():
    """Clean up the cached ignore file on process exit."""
    try:
        # Clear the cache and remove any existing temp file
        cache_info = _get_grep_ignore_file.cache_info()
        if cache_info.hits > 0 or cache_info.misses > 0:
            ignore_file = _get_grep_ignore_file()
            if ignore_file and os.path.exists(ignore_file):
                os.unlink(ignore_file)
                _get_grep_ignore_file.cache_clear()
    except Exception:
        pass  # Ignore cleanup errors on exit


# Common home directory subdirectories - hoisted to module level for efficiency
_COMMON_HOME_SUBDIRS = frozenset(
    {
        "Documents",
        "Desktop",
        "Downloads",
        "Pictures",
        "Music",
        "Videos",
        "Movies",
        "Public",
        "Library",
        "Applications",  # Cover macOS/Linux
    }
)

# SECURITY FIX 8c0/egh: Sensitive path data - module-level frozensets for O(1) lookup
# (was being rebuilt on every validate_file_path call)
_SENSITIVE_DIR_PREFIXES = frozenset(
    {
        os.path.join(os.path.expanduser("~"), ".ssh") + os.sep,
        os.path.join(os.path.expanduser("~"), ".aws") + os.sep,
        os.path.join(os.path.expanduser("~"), ".gnupg") + os.sep,
        os.path.join(os.path.expanduser("~"), ".gcp") + os.sep,
        os.path.join(os.path.expanduser("~"), ".config", "gcloud") + os.sep,
        os.path.join(os.path.expanduser("~"), ".azure") + os.sep,
        os.path.join(os.path.expanduser("~"), ".kube") + os.sep,
        os.path.join(os.path.expanduser("~"), ".docker") + os.sep,
    }
)

_SENSITIVE_EXACT_FILES = frozenset(
    {
        os.path.join(os.path.expanduser("~"), ".netrc"),
        os.path.join(os.path.expanduser("~"), ".pgpass"),
        os.path.join(os.path.expanduser("~"), ".my.cnf"),
        os.path.join(os.path.expanduser("~"), ".env"),
        os.path.join(os.path.expanduser("~"), ".bash_history"),
        os.path.join(os.path.expanduser("~"), ".npmrc"),
        os.path.join(os.path.expanduser("~"), ".pypirc"),
        os.path.join(os.path.expanduser("~"), ".gitconfig"),
        "/etc/shadow",
        "/etc/sudoers",
        "/etc/master.passwd",  # BSD/macOS
        "/etc/passwd",
        # macOS /private/etc symlinks (realpath resolves /etc -> /private/etc)
        "/private/etc/shadow",
        "/private/etc/sudoers",
        "/private/etc/master.passwd",
        "/private/etc/passwd",
    }
)

# SECURITY FIX b26: Also block project-local .env files anywhere
# Block .env and .env.* variants (.env.local, .env.production, etc.)
# BUT allow .env.example, .env.sample, .env.template (safe documentation files)
_SENSITIVE_FILENAMES = frozenset({".env"})
# Catches .env.local, .env.production, etc. but allows .env.example/.sample/.template
_ALLOWED_ENV_PATTERNS = frozenset({".env.example", ".env.sample", ".env.template"})
_SENSITIVE_FILENAME_PREFIXES = frozenset({".env."})

_SENSITIVE_EXTENSIONS = frozenset({".pem", ".key", ".p12", ".pfx", ".keystore"})


class ListFileOutput(BaseModel):
    content: str
    error: str | None = None


class ReadFileOutput(BaseModel):
    content: str | None
    num_tokens: int  # estimated token count (no upper bound — large files are valid)
    error: str | None = None


class MatchInfo(BaseModel):
    file_path: str | None
    line_number: int | None
    line_content: str | None


class GrepOutput(BaseModel):
    matches: list[MatchInfo]
    error: str | None = None


def is_likely_home_directory(directory):
    """Detect if directory is likely a user's home directory or common home subdirectory"""
    abs_dir = os.path.abspath(directory)
    home_dir = os.path.expanduser("~")

    # Exact home directory match
    if abs_dir == home_dir:
        return True

    # Check for common home directory subdirectories
    if (
        os.path.basename(abs_dir) in _COMMON_HOME_SUBDIRS
        and os.path.dirname(abs_dir) == home_dir
    ):
        return True

    return False


def is_project_directory(directory):
    """Quick heuristic to detect if this looks like a project directory"""
    project_indicators = {
        "package.json",
        "pyproject.toml",
        "Cargo.toml",
        "pom.xml",
        "build.gradle",
        "CMakeLists.txt",
        ".git",
        "requirements.txt",
        "composer.json",
        "Gemfile",
        "go.mod",
        "Makefile",
        "setup.py",
    }

    try:
        contents = os.listdir(directory)
        return any(indicator in contents for indicator in project_indicators)
    except (OSError, PermissionError):
        return False


def would_match_directory(pattern: str, directory: str) -> bool:
    """Check if a glob pattern would match the given directory path.

    This is used to avoid adding ignore patterns that would inadvertently
    exclude the directory we're actually trying to search in.

    Args:
        pattern: A glob pattern like '**/tmp/**' or 'node_modules'
        directory: The directory path to check against

    Returns:
        True if the pattern would match the directory, False otherwise
    """
    import fnmatch

    # Normalize the directory path
    abs_dir = os.path.abspath(directory)
    dir_name = os.path.basename(abs_dir)

    # Strip leading/trailing wildcards and slashes for simpler matching
    clean_pattern = pattern.strip("*").strip("/")

    # Check if the directory name matches the pattern
    if fnmatch.fnmatch(dir_name, clean_pattern):
        return True

    # Check if the full path contains the pattern
    if fnmatch.fnmatch(abs_dir, pattern):
        return True

    # Check if any part of the path matches
    path_parts = abs_dir.split(os.sep)
    for part in path_parts:
        if fnmatch.fnmatch(part, clean_pattern):
            return True

    return False


@functools.lru_cache(maxsize=512)
def get_file_icon(file_path: str) -> str:
    """Return an emoji icon based on file extension."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in [".py", ".pyw"]:
        return "\U0001f40d"
    elif ext in [".js", ".jsx", ".ts", ".tsx"]:
        return "\U0001f4dc"
    elif ext in [".html", ".htm", ".xml"]:
        return "\U0001f310"
    elif ext in [".css", ".scss", ".sass"]:
        return "\U0001f3a8"
    elif ext in [".md", ".markdown", ".rst"]:
        return "\U0001f4dd"
    elif ext in [".json", ".yaml", ".yml", ".toml"]:
        return "\u2699\ufe0f"
    elif ext in [".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"]:
        return "\U0001f5bc\ufe0f"
    elif ext in [".mp3", ".wav", ".ogg", ".flac"]:
        return "\U0001f3b5"
    elif ext in [".mp4", ".avi", ".mov", ".webm"]:
        return "\U0001f3ac"
    elif ext in [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"]:
        return "\U0001f4c4"
    elif ext in [".zip", ".tar", ".gz", ".rar", ".7z"]:
        return "\U0001f4e6"
    elif ext in [".exe", ".dll", ".so", ".dylib"]:
        return "\u26a1"
    else:
        return "\U0001f4c4"


async def _list_files(
    context: RunContext, directory: str = ".", recursive: bool = True
) -> ListFileOutput:
    import sys

    results = []
    seen_dirs = set()  # Track seen directories for O(1) duplicate check
    directory = os.path.abspath(os.path.expanduser(directory))

    # SECURITY: Validate directory path before listing
    is_valid, error_msg = validate_file_path(directory, "list")
    if not is_valid:
        return ListFileOutput(content=f"Security: {error_msg}", error=f"Security: {error_msg}")

    # Plain text output for LLM consumption
    output_lines = []
    output_lines.append(f"DIRECTORY LISTING: {directory} (recursive={recursive})")

    if not os.path.exists(directory):
        error_msg = f"Error: Directory '{directory}' does not exist"
        return ListFileOutput(content=error_msg, error=error_msg)
    if not os.path.isdir(directory):
        error_msg = f"Error: '{directory}' is not a directory"
        return ListFileOutput(content=error_msg, error=error_msg)

    # Smart home directory detection - auto-limit recursion for performance
    # But allow recursion in tests (when context=None) or when explicitly requested
    if context is not None and is_likely_home_directory(directory) and recursive:
        if not is_project_directory(directory):
            output_lines.append(
                "Warning: Detected home directory - limiting to non-recursive listing for performance"
            )
            recursive = False

    # PERFORMANCE: Track whether we truncated due to too many files
    truncated_early = False

    try:
        # Find ripgrep executable - first check system PATH, then virtual environment
        rg_path = shutil.which("rg")
        if not rg_path:
            # Try to find it in the virtual environment
            # Use sys.executable to determine the Python environment path
            python_dir = os.path.dirname(sys.executable)
            # python_dir is already bin/ (Unix) or Scripts/ (Windows)
            for name in ["rg", "rg.exe"]:
                candidate = os.path.join(python_dir, name)
                if os.path.exists(candidate):
                    rg_path = candidate
                    break

        if not rg_path and recursive:
            # Only need ripgrep for recursive listings
            error_msg = format_missing_tool_message(
                "ripgrep", context="needed for recursive file listing"
            )
            return ListFileOutput(content=error_msg, error=error_msg)

        # Only use ripgrep for recursive listings
        if recursive:
            # Build command for ripgrep --files
            cmd = [rg_path, "--files"]

            # Add ignore patterns via cached tempfile (avoids 213 writes per call)
            # Note: We skip the would_match_directory filtering for performance.
            # In practice, patterns like node_modules don't match search directories.
            ignore_file = _get_grep_ignore_file()
            cmd.extend(["--ignore-file", ignore_file])
            cmd.append(directory)

            # Run ripgrep to get file listing in a thread pool to avoid blocking the event loop
            def _run_ripgrep_list():
                return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            result = await asyncio.to_thread(_run_ripgrep_list)

            # Process the output lines
            files = result.stdout.strip().split("\n") if result.stdout.strip() else []

            # PERFORMANCE: Early exit if too many files
            if len(files) > MAX_LIST_FILES_ENTRIES:
                files = files[:MAX_LIST_FILES_ENTRIES]
                truncated_early = True

            # Create ListedFile objects with metadata
            for full_path in files:
                if not full_path:  # Skip empty lines
                    continue

                # Extract relative path from the full path
                if full_path.startswith(directory):
                    file_path = full_path[len(directory) :].lstrip(os.sep)
                else:
                    file_path = full_path

                # Single stat call for type and size - avoids 3-5 syscalls per file
                try:
                    stat_info = os.stat(full_path)
                except (FileNotFoundError, OSError):
                    continue

                # Derive type from stat mode bits
                if stat.S_ISREG(stat_info.st_mode):
                    entry_type = "file"
                    size = stat_info.st_size
                elif stat.S_ISDIR(stat_info.st_mode):
                    entry_type = "directory"
                    size = 0
                else:
                    # Skip if it's neither a file nor directory
                    continue

                # Calculate depth based on the relative path
                depth = file_path.count(os.sep)

                # PERFORMANCE FIX 2np/hlc: O(depth) parent-path construction
                # Add directory entries if needed for files
                if entry_type == "file":
                    dir_path = os.path.dirname(file_path)
                    if dir_path:
                        # Add directory path components if they don't exist
                        # Using seen_dirs set (defined at function scope) for O(1) lookup
                        # Accumulate paths efficiently instead of O(depth²) repeated joins
                        path_parts = dir_path.split(os.sep)
                        partial_path = ""
                        for i, part in enumerate(path_parts):
                            if i == 0:
                                partial_path = part
                            else:
                                partial_path = partial_path + os.sep + part
                            # Check if we already added this directory using set
                            if partial_path not in seen_dirs:
                                seen_dirs.add(partial_path)
                                results.append(
                                    ListedFile(
                                        path=partial_path,
                                        type="directory",
                                        size=0,
                                        full_path=os.path.join(directory, partial_path),
                                        depth=i,  # depth is just the index
                                    )
                                )

                # Add the entry (file or directory)
                results.append(
                    ListedFile(
                        path=file_path,
                        type=entry_type,
                        size=size,
                        full_path=full_path,
                        depth=depth,
                    )
                )

        # In non-recursive mode, we also need to explicitly list immediate entries
        # ripgrep's --files option only returns files; we add directories and files ourselves
        if not recursive:
            try:
                entries = os.listdir(directory)
                for entry in entries:
                    full_entry_path = os.path.join(directory, entry)
                    if not os.path.exists(full_entry_path):
                        continue

                    if os.path.isdir(full_entry_path):
                        # In non-recursive mode, only skip obviously system/hidden directories
                        # Don't use the full should_ignore_dir_path which is too aggressive
                        if entry.startswith("."):
                            continue
                        results.append(
                            ListedFile(
                                path=entry,
                                type="directory",
                                size=0,
                                full_path=full_entry_path,
                                depth=0,
                            )
                        )
                    elif os.path.isfile(full_entry_path):
                        # Include top-level files (including binaries)
                        try:
                            size = os.path.getsize(full_entry_path)
                        except OSError:
                            size = 0
                        results.append(
                            ListedFile(
                                path=entry,
                                type="file",
                                size=size,
                                full_path=full_entry_path,
                                depth=0,
                            )
                        )
            except (FileNotFoundError, PermissionError, OSError):
                # Skip entries we can't access
                pass
    except subprocess.TimeoutExpired:
        error_msg = "Error: List files command timed out after 30 seconds"
        return ListFileOutput(content=error_msg, error=error_msg)
    except Exception as e:
        error_msg = f"Error: Error during list files operation: {e}"
        return ListFileOutput(content=error_msg, error=error_msg)
    # Note: Ignore file cleanup is handled by _cleanup_ignore_file atexit handler

    # PERFORMANCE: Warn if we truncated the file list
    if truncated_early:
        output_lines.append(f"\n⚠️  TRUNCATED: Listing limited to first {MAX_LIST_FILES_ENTRIES} files for performance.")

    # Gitignore filtering (HIGHER-RISK: bd code_puppy-31a.9)
    # Only filter if explicitly enabled in config (defaults to OFF for safety)
    from code_puppy.config import get_enable_gitignore_filtering

    if get_enable_gitignore_filtering():
        results = [
            f for f in results if not is_gitignored(f.full_path, base_dir=directory)
        ]

    # Count items in results - single pass for performance
    dir_count = 0
    file_count = 0
    total_size = 0
    for item in results:
        if item.type == "directory":
            dir_count += 1
        else:
            file_count += 1
            total_size += item.size

    def _sort_key(item):
        """Sort by path components to keep children grouped under parents.

        Splitting on os.sep ensures 'src/foo' always sorts right after 'src'
        rather than letting 'src-tauri' (with '-' < '/') slip in between.
        Directories sort before files at the same level.
        """
        parts = item.path.split(os.sep)
        return (parts, item.type != "directory")

    # Sort once and iterate once - fused single pass for both UI and text output
    sorted_results = sorted(results, key=_sort_key)

    # Fused single pass: build both file_entries and output_lines in one iteration
    file_entries = []
    for item in sorted_results:
        if item.type == "directory" and not item.path:
            continue

        # Build FileEntry for structured UI message
        file_entries.append(
            FileEntry(
                path=item.path,
                type="dir" if item.type == "directory" else "file",
                size=item.size,
                depth=item.depth or 0,
            )
        )

        # Build plain text line for LLM consumption
        name = os.path.basename(item.path) or item.path
        indent = "  " * (item.depth or 0)
        if item.type == "directory":
            output_lines.append(f"{indent}{name}/")
        else:
            size_str = format_size(item.size)
            output_lines.append(f"{indent}{name} ({size_str})")

    # PERFORMANCE: Cap file_entries to prevent huge structured messages
    if len(file_entries) > MAX_LIST_FILES_ENTRIES:
        file_entries = file_entries[:MAX_LIST_FILES_ENTRIES]

    # Emit structured message for the UI
    file_listing_msg = FileListingMessage(
        directory=directory,
        files=file_entries,
        recursive=recursive,
        total_size=total_size,
        dir_count=dir_count,
        file_count=file_count,
    )
    get_message_bus().emit(file_listing_msg)

    # Add summary
    output_lines.append(
        f"\nSummary: {dir_count} directories, {file_count} files ({format_size(total_size)} total)"
    )

    return ListFileOutput(content="\n".join(output_lines))


# ---------------------------------------------------------------------------
# Security helpers
# SECURITY FIX peis/wslg/p8wo/8y6x: path validation & sensitive-path blocking
# ---------------------------------------------------------------------------


def _is_sensitive_path(file_path: str) -> bool:
    """Check if a path points to a sensitive file/directory.

    Used by file_operations and the file_permission_handler plugin to block
    access to credentials, SSH keys, and other secrets — even in yolo_mode.

    SECURITY FIX peis/wslg/p8wo/8y6x: sensitive-path blocklist.
    PERFORMANCE FIX 8c0/egh: Uses module-level frozensets for O(1) lookup.

    Args:
        file_path: Path to check (may be relative, absolute, or contain ~).

    Returns:
        True if the path points to a sensitive location and should be blocked.
    """
    if not file_path:
        return False

    # Normalize: expand ~, resolve symlinks, make absolute
    try:
        expanded = os.path.abspath(os.path.expanduser(file_path))
        # Resolve symlinks so we catch symlink-based bypass attempts.
        # Use realpath which doesn't require the file to exist.
        resolved = os.path.realpath(expanded)
    except (OSError, ValueError):
        # If we can't normalize, treat it as NOT sensitive (let other
        # checks handle invalid paths); validate_file_path will catch
        # genuinely bad input.
        return False

    # Check directory prefixes (with trailing separator to avoid
    # "/home/user/.sshfoo" matching "/home/user/.ssh")
    # SECURITY FIX: Also check exact directory match (e.g., "/home/user/.ssh")
    for prefix in _SENSITIVE_DIR_PREFIXES:
        if resolved.startswith(prefix):
            return True
        # Check exact directory match (prefix without trailing slash)
        exact_dir = prefix.rstrip(os.sep)
        if resolved == exact_dir:
            return True

    # Check exact-match files
    if resolved in _SENSITIVE_EXACT_FILES:
        return True

    # SECURITY FIX b26: Block sensitive filenames anywhere (e.g., .env)
    basename = os.path.basename(resolved)
    if basename in _SENSITIVE_FILENAMES:
        return True
    # Block .env.* variants (lowercase comparison for case-insensitive match)
    # BUT allow .env.example, .env.sample, .env.template (safe documentation)
    basename_lower = basename.lower()
    if basename_lower in _ALLOWED_ENV_PATTERNS:
        return False  # Explicitly allow these safe documentation files
    if any(
        basename_lower.startswith(prefix) for prefix in _SENSITIVE_FILENAME_PREFIXES
    ):
        return True

    # Check for private key files by extension anywhere (SECURITY FIX b26)
    # Previously only blocked if parent directory had credential-ish names,
    # but deploy.key, server.pem, etc. anywhere can contain secrets.
    _, ext = os.path.splitext(resolved)
    if ext.lower() in _SENSITIVE_EXTENSIONS:
        return True

    return False


def validate_file_path(file_path: str, operation: str) -> tuple[bool, str | None]:
    """Validate a file path before performing an operation on it.

    SECURITY FIX peis/wslg: path validation + sensitive-path blocking.

    Checks performed:
      1. Non-empty string
      2. No null bytes (directory traversal / injection attempts)
      3. Not a sensitive path (SSH keys, AWS creds, etc.)

    Args:
        file_path: The path the tool wants to access.
        operation: The operation being performed ("read", "write", "delete", etc.).
                   Currently used only for error messages; may be used for
                   operation-specific policy in the future.

    Returns:
        (is_valid, error_message) tuple:
          - (True, None)  if the path passes all checks
          - (False, "...") with a human-readable reason otherwise
    """
    if not file_path or not isinstance(file_path, str):
        return False, "File path cannot be empty"

    # Null byte check — prevents C-string truncation tricks
    if "\x00" in file_path:
        return False, "File path contains null byte"

    # Sensitive-path blocklist (enforced for all operations,
    # including reads, because even read-only access to ~/.ssh/id_rsa
    # is a credential-exfiltration vector).
    if _is_sensitive_path(file_path):
        return (
            False,
            f"Access to sensitive path blocked ({operation}): "
            "SSH keys, cloud credentials, and system secrets are never accessible.",
        )

    return True, None


async def _read_file(
    context: RunContext,
    file_path: str,
    start_line: int | None = None,
    num_lines: int | None = None,
) -> ReadFileOutput:
    """Read file with concurrency limiting and security validation.

    SECURITY FIX peis/wslg: Added path validation before file access.
    """
    # Validate path before accessing
    is_valid, error_msg = validate_file_path(file_path, "read")
    if not is_valid:
        return ReadFileOutput(
            content=None, num_tokens=0, error=f"Security: {error_msg}"
        )

    async with FileOpsLimiter():
        # Run blocking I/O in thread pool
        content, num_tokens, error = await asyncio.to_thread(
            _read_file_sync, file_path, start_line, num_lines
        )
        return ReadFileOutput(content=content, num_tokens=num_tokens, error=error)


def _read_file_sync(
    file_path: str, start_line: int | None = None, num_lines: int | None = None
) -> tuple[str | None, int, str | None]:
    """Synchronous file reading - runs in thread pool.

    SECURITY FIX peis/wslg: Normalizes path.
    PERFORMANCE FIX 25g/c6w: Path validation happens in _read_file, not duplicated here.
    """
    # SECURITY: Normalize path (validation done in _read_file before thread pool dispatch)
    file_path = os.path.abspath(os.path.expanduser(file_path))

    # Try macOS path variants if file not found (handles screenshot
    # filenames with NFD encoding, narrow NBSP, curly quotes)
    if not os.path.exists(file_path):
        file_path = resolve_path_with_variants(file_path)

    if not os.path.exists(file_path):
        error_msg = f"File {file_path} does not exist"
        return "", 0, error_msg
    if not os.path.isfile(file_path):
        error_msg = f"{file_path} is not a file"
        return "", 0, error_msg
    try:
        # Use errors="surrogateescape" to handle files with invalid UTF-8 sequences
        # This is common on Windows when files contain emojis or were created by
        # applications that don't properly encode Unicode
        with open(file_path, "r", encoding="utf-8", errors="surrogateescape") as f:
            if start_line is not None and start_line < 1:
                error_msg = "start_line must be >= 1 (1-based indexing)"
                return "", 0, error_msg
            if num_lines is not None and num_lines < 1:
                error_msg = "num_lines must be >= 1"
                return "", 0, error_msg
            if start_line is not None and num_lines is not None:
                # Read only the specified lines efficiently using itertools.islice
                # to avoid loading the entire file into memory
                import itertools

                start_idx = start_line - 1
                selected_lines = list(
                    itertools.islice(f, start_idx, start_idx + num_lines)
                )
                content = "".join(selected_lines)
            else:
                # Read the entire file
                content = f.read()

            # PERFORMANCE FIX esd/5zl: Fast surrogate cleanup using encode/decode
            # instead of slow per-character Python loop.
            # Sanitize the content to remove any surrogate characters that could
            # cause issues when the content is later serialized or displayed.
            # This re-encodes with surrogatepass then decodes with replace to
            # convert lone surrogates to replacement characters.
            content = content.encode("utf-8", errors="surrogatepass").decode(
                "utf-8", errors="replace"
            )

            # EOL normalization: CRLF → LF for text files, binary passthrough.
            # Ported from plandex shared/utils.go NormalizeEOL.
            content = normalize_eol(content)

            # BOM stripping: remove invisible BOM that confuses LLMs
            # (the model should see clean content without encoding markers)
            content, _ = strip_bom(content)  # Discard BOM on read — LLM shouldn't see it

            # Use accurate token counting via tiktoken (provider-aware)
            # gpt-4o is a good middle-ground tokenizer for estimation
            num_tokens = count_tokens(content, model_name="gpt-4o")
            if num_tokens > MAX_READ_FILE_TOKENS:
                return (
                    None,
                    0,
                    f"The file is massive, greater than {MAX_READ_FILE_TOKENS:,} tokens which is dangerous to read entirely. Please read this file in chunks.",
                )

            # Count total lines for the message
            total_lines = content.count("\n") + (
                1 if content and not content.endswith("\n") else 0
            )

            # Emit structured message for the UI
            # Only include start_line/num_lines if they are valid positive integers
            emit_start_line = (
                start_line if start_line is not None and start_line >= 1 else None
            )
            emit_num_lines = (
                num_lines if num_lines is not None and num_lines >= 1 else None
            )
            file_content_msg = FileContentMessage(
                path=file_path,
                content=content,
                start_line=emit_start_line,
                num_lines=emit_num_lines,
                total_lines=total_lines,
                num_tokens=num_tokens,
            )
            get_message_bus().emit(file_content_msg)

        return content, num_tokens, None
    except FileNotFoundError:
        error_msg = "FILE NOT FOUND"
        return "", 0, error_msg
    except PermissionError:
        error_msg = "PERMISSION DENIED"
        return "", 0, error_msg
    except Exception as e:
        message = f"An error occurred trying to read the file: {e}"
        return message, 0, message


def _sanitize_string(text: str) -> str:
    """Sanitize a string to remove invalid Unicode surrogates.

    This handles encoding issues common on Windows with copy-paste operations.
    PERFORMANCE FIX esd/5zl: Uses encode/decode in one pass instead of slow loop.
    """
    if not text:
        return text
    # Fast path: try encoding - if it works, string is clean
    try:
        text.encode("utf-8")
        return text
    except UnicodeEncodeError:
        pass

    # PERFORMANCE FIX esd/5zl: Single-pass encode/decode instead of per-char loop
    return text.encode("utf-8", errors="surrogatepass").decode(
        "utf-8", errors="replace"
    )


async def _grep(
    context: RunContext, search_string: str, directory: str = "."
) -> GrepOutput:
    import json
    import shlex
    import shutil
    import subprocess
    import sys

    # Sanitize search string to handle any surrogates from copy-paste
    search_string = _sanitize_string(search_string)

    directory = os.path.abspath(os.path.expanduser(directory))

    # SECURITY: Validate directory path before searching
    is_valid, error_msg = validate_file_path(directory, "search")
    if not is_valid:
        return GrepOutput(matches=[], error=f"Security: {error_msg}")

    matches: list[MatchInfo] = []
    error_message: str | None = None

    try:
        # Use ripgrep to search for the string
        # Use absolute path to ensure it works from any directory
        # --json for structured output
        # --max-count MAX_GREP_MATCHES to limit results
        # --max-filesize MAX_GREP_FILE_SIZE_BYTES to avoid huge files
        # --type=all to search across all recognized text file types
        # --ignore-file to obey our ignore list

        # Find ripgrep executable - first check system PATH, then virtual environment
        rg_path = shutil.which("rg")
        if not rg_path:
            # Try to find it in the virtual environment
            # Use sys.executable to determine the Python environment path
            python_dir = os.path.dirname(sys.executable)
            # python_dir is already bin/ (Unix) or Scripts/ (Windows)
            for name in ["rg", "rg.exe"]:
                candidate = os.path.join(python_dir, name)
                if os.path.exists(candidate):
                    rg_path = candidate
                    break

        if not rg_path:
            error_message = format_missing_tool_message(
                "ripgrep", context="needed for grep searches"
            )
            return GrepOutput(matches=[], error=error_message)

        cmd = [
            rg_path,
            "--json",
            "--max-count",
            str(MAX_GREP_MATCHES),
            "--max-filesize",
            f"{MAX_GREP_FILE_SIZE_BYTES // (1024 * 1024)}M",
            "--type=all",
        ]

        # Add ignore patterns via cached tempfile (avoids 213 writes per call)
        ignore_file = _get_grep_ignore_file()
        cmd.extend(["--ignore-file", ignore_file])
        # Split search_string to support ripgrep flags like --ignore-case
        try:
            parts = shlex.split(search_string)
        except ValueError:
            # Fallback for unmatched quotes (e.g., apostrophes in search terms)
            parts = [search_string]
        cmd.extend(parts)
        cmd.append(directory)

        # Run ripgrep in a thread pool to avoid blocking the event loop
        def _run_ripgrep():
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
                errors="replace",  # Replace invalid chars instead of crashing
            )

        result = await asyncio.to_thread(_run_ripgrep)

        # Parse the JSON output from ripgrep
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                match_data = json.loads(line)
                # Only process match events, not context or summary
                if match_data.get("type") == "match":
                    data = match_data.get("data", {})
                    path_data = data.get("path", {})
                    file_path = (
                        path_data.get("text", "") if path_data.get("text") else ""
                    )
                    line_number = data.get("line_number", None)
                    line_content = (
                        data.get("lines", {}).get("text", "")
                        if data.get("lines", {}).get("text")
                        else ""
                    )
                    stripped = line_content.strip()
                    if len(stripped) > 512:
                        stripped = stripped[0:512]
                    if file_path and line_number:
                        # Sanitize content to handle any remaining encoding issues
                        match_info = MatchInfo(
                            file_path=_sanitize_string(file_path),
                            line_number=line_number,
                            line_content=_sanitize_string(stripped),
                        )
                        matches.append(match_info)
                        # Limit to MAX_GREP_MATCHES total
                        if len(matches) >= MAX_GREP_MATCHES:
                            break
            except json.JSONDecodeError:
                # Skip lines that aren't valid JSON
                continue

    except subprocess.TimeoutExpired:
        error_message = "Grep command timed out after 30 seconds"
    except FileNotFoundError:
        error_message = (
            "ripgrep (rg) not found. Please install ripgrep to use this tool."
        )
    except Exception as e:
        error_message = f"Error during grep operation: {e}"
    # Note: Ignore file cleanup is handled by _cleanup_ignore_file atexit handler

    # SECURITY: Filter out matches from sensitive files
    filtered_matches = []
    for match in matches:
        match_valid, _ = validate_file_path(match.file_path, "search-result")
        if match_valid:
            filtered_matches.append(match)
    matches = filtered_matches

    # Build structured GrepMatch objects for the UI
    grep_matches = [
        GrepMatch(
            file_path=m.file_path or "",
            line_number=m.line_number or 1,
            line_content=m.line_content or "",
        )
        for m in matches
    ]

    # Count unique files searched (approximation based on matches)
    unique_files = len(set(m.file_path for m in matches)) if matches else 0

    # Emit structured message for the UI (only once, at the end)
    grep_result_msg = GrepResultMessage(
        search_term=search_string,
        directory=directory,
        matches=grep_matches,
        total_matches=len(matches),
        files_searched=unique_files,
    )
    get_message_bus().emit(grep_result_msg)

    return GrepOutput(matches=matches, error=error_message)


def register_list_files(agent):
    """Register only the list_files tool."""
    from code_puppy.config import get_allow_recursion

    @agent.tool
    async def list_files(
        context: RunContext, directory: str = ".", recursive: bool = True
    ) -> ListFileOutput:
        """List files and directories with intelligent filtering and safety features.

        Automatically ignores build artifacts, caches, and common noise.
        """
        warning = None
        if recursive and not get_allow_recursion():
            warning = "Recursion disabled globally for list_files - returning non-recursive results"
            recursive = False
        result = await _list_files(context, directory, recursive)

        # The structured FileListingMessage is already emitted by _list_files
        # No need to emit again here
        if warning:
            result.error = warning
        # ADOPT #6: Truncate with helpful guidance message
        if len(result.content) > 200000:
            result.content = truncate_with_guidance(
                result.content, limit_chars=200000, tool_name="list_files"
            )
            result.error = "Results truncated. This is a massive directory tree, recommend non-recursive calls to list_files"
        return result


def register_read_file(agent):
    """Register only the read_file tool."""

    @agent.tool
    async def read_file(
        context: RunContext,
        file_path: str = "",
        start_line: int | None = None,
        num_lines: int | None = None,
        format_line_numbers: bool = False,
    ) -> ReadFileOutput:
        """Read file contents with optional line-range selection and token safety.

        Use start_line/num_lines for large files to avoid overwhelming context.
        Set format_line_numbers=True to get cat -n style line numbering with
        continuation markers for very long lines (>5000 chars).
        """
        result = await _read_file(context, file_path, start_line, num_lines)

        # ADOPT #4: Optional line number formatting with continuation for long lines
        if format_line_numbers and result.content and not result.error:
            effective_start = start_line if start_line is not None else 1
            result.content = format_content_with_line_numbers(
                result.content, start_line=effective_start
            )

        return result


def register_grep(agent):
    """Register only the grep tool."""

    @agent.tool
    async def grep(
        context: RunContext, search_string: str = "", directory: str = "."
    ) -> GrepOutput:
        """Recursively search for text patterns across files using ripgrep (rg).

        search_string supports ripgrep flag syntax (regex, -i for case-insensitive, etc).
        """
        return await _grep(context, search_string, directory)
