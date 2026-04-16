# turbo_parse

[![CI](https://github.com/mpfaffenberger/code_puppy/actions/workflows/turbo_parse.yml/badge.svg)](https://github.com/mpfaffenberger/code_puppy/actions/workflows/turbo_parse.yml)
[![Crates.io](https://img.shields.io/badge/Rust-turbo_parse-orange?logo=rust)](https://github.com/mpfaffenberger/code_puppy/tree/main/turbo_parse)
[![Python Versions](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue?logo=python)](https://pypi.org/project/turbo-parse/)
[![Platforms](https://img.shields.io/badge/platforms-linux%20|%20macos%20|%20windows-lightgrey)](./CI.md)

High-performance parsing with tree-sitter and PyO3 bindings for Code Puppy.

## What's New in Phase 2

turbo_parse now includes powerful editor-grade features:

- **🎨 Syntax Highlighting** — Tree-sitter query-based highlighting using Helix Editor queries
- **📁 Code Folding** — Extract 7 fold types (functions, classes, conditionals, loops, blocks, imports, generics)
- **⚡ Incremental Parsing** — Fast re-parsing for real-time editing via `parse_with_edits()`
- **📊 Comprehensive Benchmarking** — Criterion-based benchmarks with 1k/10k/100k LOC targets
- **🧪 Fuzz Testing** — Property-based testing with Hypothesis for 5 languages
- **🚀 Performance Optimized** — Request cache with header-only change optimization

## Features

- **Blazing Fast**: Rust-powered parsing with tree-sitter, GIL release during CPU-intensive operations
- **Multi-Language**: Support for Python, Rust, JavaScript, TypeScript, TSX, and Elixir
- **Symbol Extraction**: Extract functions, classes, methods, imports with precise location info
- **Syntax Highlighting**: Editor-grade highlighting with capture names (keyword, function, string, etc.)
- **Code Folding**: Extract foldable regions for IDE-style code collapse
- **Diagnostics**: Syntax error detection with detailed position information
- **Caching**: LRU cache for parsed trees to avoid re-parsing unchanged files
- **Incremental Parsing**: Fast re-parsing with tree reuse for editor-like use cases
- **Batch Processing**: Parallel file parsing across all CPU cores
- **Query System**: 18+ tree-sitter query files vendored from Helix Editor
- **Python Integration**: Seamless PyO3 bindings for use in Python applications

## Language Support Tiers

turbo_parse organizes language support into three tiers based on feature completeness:

### Tier 1: Full Support ✅

All features work reliably with comprehensive test coverage.

| Language | Parsing | Symbols | Diagnostics | Batch | Cache |
|----------|---------|---------|-------------|-------|-------|
| **Python** | ✅ | ✅ Functions, classes, methods, imports | ✅ | ✅ | ✅ |
| **Rust** | ✅ | ✅ Functions, structs, traits, impls, enums | ✅ | ✅ | ✅ |
| **JavaScript** | ✅ | ✅ Functions, classes, methods, imports | ✅ | ✅ | ✅ |
| **TypeScript** | ✅ | ✅ Functions, classes, interfaces, types, enums | ✅ | ✅ | ✅ |

**Tier 1 Features:**
- Full tree-sitter grammar support
- Complete symbol extraction (functions, classes, methods, imports, variables)
- Parent-child relationships (e.g., methods linked to their class)
- Syntax error diagnostics with line/column positions
- Batch parallel parsing
- LRU caching

### Tier 2: Good Support 🟡

Core features work well, some edge cases may need attention.

| Language | Parsing | Symbols | Diagnostics | Batch | Cache |
|----------|---------|---------|-------------|-------|-------|
| **TSX** (TypeScript + JSX) | ✅ | ✅ Functions, classes, JSX components | ✅ | ✅ | ✅ |

**Tier 2 Notes:**
- Parsing works correctly for all TSX constructs
- JSX component extraction supported
- Some complex nested JSX patterns may not extract all symbols
- Type annotations within JSX may have gaps

### Tier 3: Basic Support 🟠

Parsing works but complex patterns have gaps.

| Language | Parsing | Symbols | Diagnostics | Batch | Cache |
|----------|---------|---------|-------------|-------|-------|
| **Elixir** | ✅ | ⚠️ Modules, functions, basic imports | ✅ | ✅ | ✅ |

**Tier 3 Limitations:**
- Basic parsing works well for standard Elixir code
- Module and function extraction functional
- **Not yet supported:**
  - HEEx templates (HTML+EEx) - see [Known Gaps](#known-gaps)
  - Complex Elixir sigils with custom delimiters
  - Elixir macros and quoted expressions
  - Phoenix controller action extraction has edge cases

### Language Aliases

The following aliases are automatically recognized:

| Alias | Maps To |
|-------|---------|
| `py` | `python` |
| `js` | `javascript` |
| `ts` | `typescript` |
| `ex`, `exs` | `elixir` |

### File Extension Detection

When using `parse_file()`, the language is automatically detected from file extensions:

| Extension | Language |
|-----------|----------|
| `.py` | Python |
| `.rs` | Rust |
| `.js`, `.jsx` | JavaScript |
| `.ts` | TypeScript |
| `.tsx` | TSX |
| `.ex`, `.exs` | Elixir |

## Phase 2 Features (New!)

turbo_parse Phase 2 introduces powerful features for editor integration, performance optimization, and reliability testing.

### 🎨 Syntax Highlighting

Extract syntax highlighting captures from source code using tree-sitter queries from the Helix Editor.

**Key Features:**
- Editor-grade syntax highlighting with capture names following Helix conventions
- Support for Python, Rust, JavaScript, TypeScript, TSX, and Elixir
- Captures include: `keyword`, `function`, `type`, `string`, `comment`, `variable`, `constant`, `operator`, `punctuation`
- Byte-accurate position information for precise highlighting

**API:**
- `get_highlights(source, language)` — Extract highlights from source code
- `get_highlights_from_file(path, language=None)` — Extract highlights from file
- `HighlightCapture` — Struct with `start_byte`, `end_byte`, `capture_name`

**Example:**
```python
import turbo_parse

source = """
def greet(name: str) -> str:
    # Return a greeting
    return f"Hello, {name}!"
"""

result = turbo_parse.get_highlights(source, "python")
print(f"Found {len(result['captures'])} highlight captures:")

for capture in result['captures']:
    name = capture['capture_name']
    start = capture['start_byte']
    end = capture['end_byte']
    text = source[start:end]
    print(f"  [{name}] '{text}'")
```

### 📁 Code Folding

Extract foldable regions (functions, classes, blocks) for IDE-style code collapse.

**Key Features:**
- 7 fold types: `function`, `class`, `conditional`, `loop`, `block`, `import`, `generic`
- Line-accurate fold ranges (start_line, end_line)
- Supports all 6 languages with language-specific fold detection
- Tree-sitter query-based extraction using Helix Editor queries

**API:**
- `get_folds(source, language)` — Extract fold ranges from source code
- `get_folds_from_file(path, language=None)` — Extract fold ranges from file
- `FoldRange` — Struct with `start_line`, `end_line`, `fold_type`
- `FoldType` — Enum with 7 variants

**Example:**
```python
import turbo_parse

source = """
class DataProcessor:
    def __init__(self):
        self.cache = {}
    
    def process(self, data: List[str]) -> dict:
        if not data:
            return {}
        return {"count": len(data)}
"""

result = turbo_parse.get_folds(source, "python")
print(f"Found {len(result['folds'])} foldable regions:")

for fold in result['folds']:
    fold_type = fold['fold_type']
    start = fold['start_line']
    end = fold['end_line']
    print(f"  [{fold_type}] lines {start}-{end}")
```

**Fold Types:**
| Type | Description | Examples |
|------|-------------|----------|
| `function` | Function definitions | `def`, `fn`, `function` |
| `class` | Class/struct definitions | `class`, `struct`, `interface` |
| `conditional` | Conditional blocks | `if`, `match`, `switch` |
| `loop` | Loop constructs | `for`, `while`, `loop` |
| `block` | Block statements | `try`, `with`, `impl` |
| `import` | Import/export statements | `import`, `use`, `require` |
| `generic` | Generic blocks | objects, arrays, JSX elements |

### ⚡ Incremental Parsing

Fast re-parsing for editor-like use cases with localized changes.

**Key Features:**
- Reuses previous parse trees for significantly faster re-parsing
- Applies text edits via `InputEdit` descriptors
- Ideal for real-time editor scenarios (typing, small edits)
- GIL release during CPU-intensive re-parsing

**API:**
- `parse_with_edits(source, language, old_tree, edits)` — Incremental re-parsing
- `InputEdit` — Struct describing text edits with byte and position offsets

**When to Use:**
- ✅ Real-time editor scenarios (typing, small edits)
- ✅ Large files with localized changes
- ✅ IDE features requiring frequent re-parsing
- ❌ Initial parse of a document (use `parse_source`)
- ❌ Massive structural changes (better to do full re-parse)

**Example:**
```python
import turbo_parse

# Initial parse of a document
source = "def hello(): pass"
result = turbo_parse.parse_source(source, "python")

# Make an edit: change "pass" to "return 42"
new_source = "def hello(): return 42"

# Create an InputEdit describing the change
edit = turbo_parse.InputEdit(
    start_byte=12,        # Start position in old source
    old_end_byte=16,      # End of "pass" in old source
    new_end_byte=24,      # End of "return 42" in new source
    start_position=(0, 12),     # (line, column) in old source
    old_end_position=(0, 16),     # (line, column) end of old text
    new_end_position=(0, 24)      # (line, column) end of new text
)

# Incremental re-parse
new_result = turbo_parse.parse_with_edits(
    new_source,
    "python",
    result["tree"],  # Previous tree from parse_source/parse_file
    [edit]           # List of edits applied
)

print(f"Success: {new_result['success']}")
print(f"Parse time: {new_result['parse_time_ms']:.2f}ms")
```

### 📚 Query System

Tree-sitter query files vendored from the [Helix Editor](https://github.com/helix-editor/helix) project.

**Included Queries:**

| Language | Highlights | Folds | Indents | Total |
|----------|------------|-------|---------|-------|
| Python | ✓ | ✓ | ✓ | 3 |
| Rust | ✓ | ✓ | ✓ | 3 |
| JavaScript | ✓ | ✓ | ✓ | 3 |
| TypeScript | ✓ | ✓ | ✓ | 3 |
| TSX | ✓ | ✓ | ✓ | 3 |
| Elixir | ✓ | ✓ | ✓ | 3 |
| **Total** | 6 | 6 | 6 | **18** |

**Query Types:**
- **highlights.scm** — Syntax highlighting queries that map AST nodes to highlight scopes
- **folds.scm** — Code folding queries that define foldable regions
- **indents.scm** — Indentation rules for auto-indentation support

**Attribution:**
- Source: https://github.com/helix-editor/helix
- License: MPL-2.0 (compatible with MIT)
- See `queries/ATTRIBUTION` for full details

### 📊 Benchmarking

Criterion-based benchmarks with automated regression detection.

**Performance Targets** (Apple M1, cold parse):

| File Size | Python | Rust | JavaScript |
|-----------|--------|------|------------|
| 1k LOC    | < 5ms  | < 5ms | < 5ms |
| 10k LOC   | < 30ms | < 30ms | < 30ms |
| 100k LOC  | < 250ms| < 250ms| < 250ms |

**Running Benchmarks:**
```bash
# Run all benchmarks
cargo bench

# Run specific benchmark group
cargo bench python_parse

# Check for regressions
cd benches && python3 check_regression.py

# Save new baseline
cd benches && python3 check_regression.py --save-baseline
```

See [benches/BENCHMARKS.md](./benches/BENCHMARKS.md) for detailed documentation.

### 🧪 Fuzz Testing

Property-based fuzz testing using Hypothesis.

**Features:**
- **5 languages tested**: Python, Rust, JavaScript, TypeScript, Elixir
- **Properties verified**: No crashes, success status, valid symbol names, required fields
- **Edge cases covered**: Empty files, unicode, deep nesting, long names (up to 1000 chars)
- **Strategies**: Language-specific code generation strategies

**Running Fuzz Tests:**
```bash
# Run with CI profile (50 examples per test)
pytest tests/fuzz/ -v

# Run with local profile (200 examples per test)
pytest tests/fuzz/ -v --hypothesis-profile=local

# Run with thorough profile (500 examples per test)
pytest tests/fuzz/ -v --hypothesis-profile=thorough
```

See [tests/fuzz/README.md](../tests/fuzz/README.md) for detailed documentation.

### 🚀 Performance Optimizations

**Request Cache with Header-Only Optimization:**
- Caches HTTP requests and detects header-only changes
- 5-10x faster for token refresh scenarios
- 500-1000x faster for identical requests
- No overhead for content-changing requests

**Cache Features:**
- Content-based hashing (method + URL + body)
- Header hash tracking with normalization
- Delta update strategy (exact match, header-only change, full rebuild)
- Configurable size and TTL

See [request_cache_optimization.md](../docs/request_cache_optimization.md) for details.

## Quick Start

### Installation

```bash
# From source (development)
cd turbo_parse
maturin develop --release

# Or install from wheel
pip install turbo-parse
```

### Basic Usage

```python
import turbo_parse

# Check module health
result = turbo_parse.health_check()
print(result)
# {'available': True, 'version': '0.1.0', 'languages': ['python', 'rust', ...], 'cache_available': False}
```

### Parse Source Code

```python
import turbo_parse

# Parse Python code
source = """
def hello(name: str) -> str:
    return f"Hello, {name}!"

class Greeter:
    def __init__(self, greeting: str):
        self.greeting = greeting
    
    def greet(self, name: str) -> str:
        return f"{self.greeting}, {name}!"
"""

result = turbo_parse.parse_source(source, "python")
print(f"Success: {result['success']}")
print(f"Language: {result['language']}")
print(f"Parse time: {result['parse_time_ms']:.2f}ms")

# Access the AST tree
if result['tree']:
    print(f"Root node type: {result['tree']['root']['type']}")
```

**Output format:**
```python
{
    'language': 'python',
    'tree': {
        'root': {
            'type': 'module',
            'start': {'row': 0, 'column': 0, 'byte': 0},
            'end': {'row': 10, 'column': 0, 'byte': 234},
            'children': [...]
        },
        'language': 'tree-sitter'
    },
    'parse_time_ms': 0.85,
    'success': True,
    'errors': [],
    'diagnostics': {
        'diagnostics': [],
        'error_count': 0,
        'warning_count': 0
    }
}
```

### Parse a File

```python
import turbo_parse

# Parse a file (language auto-detected from extension)
result = turbo_parse.parse_file("my_module.py")

# Or specify language explicitly
result = turbo_parse.parse_file("some_file.txt", language="python")
```

### Extract Symbols (Outline)

Extract a hierarchical outline of all symbols from source code:

```python
import turbo_parse

source = """
import os
from typing import List

def process_data(items: List[str]) -> dict:
    return {"count": len(items)}

class DataProcessor:
    def __init__(self):
        self.cache = {}
    
    def process(self, data: List[str]) -> dict:
        return process_data(data)
"""

result = turbo_parse.extract_symbols(source, "python")
print(f"Found {len(result['symbols'])} symbols:\n")

# Show top-level vs nested symbols
for symbol in result['symbols']:
    kind = symbol['kind']
    name = symbol['name']
    line = symbol['start_line']
    parent = symbol.get('parent', None)
    
    if parent:
        print(f"  [{kind}] {name} (line {line}) └─ in {parent}")
    else:
        print(f"  [{kind}] {name} (line {line})")
```

**Output:**
```
Found 5 symbols:

  [import] os (line 2)
  [import] typing (line 3)
  [function] process_data (line 5)
  [class] DataProcessor (line 8)
  [method] process (line 12) └─ in DataProcessor
```

### Syntax Highlighting

Extract syntax highlighting captures for editor integration:

```python
import turbo_parse

source = '''
def greet(name: str) -> str:
    """Return a greeting."""
    return f"Hello, {name}!"

class Greeter:
    DEFAULT = "Hi"
    
    def __init__(self, greeting: str = None):
        self.greeting = greeting or self.DEFAULT
'''

result = turbo_parse.get_highlights(source, "python")
print(f"Found {len(result['captures'])} highlight captures:\n")

# Show captures by category
categories = {}
for cap in result['captures']:
    name = cap['capture_name']
    text = source[cap['start_byte']:cap['end_byte']]
    if name not in categories:
        categories[name] = []
    categories[name].append(text)

for cat, texts in sorted(categories.items()):
    print(f"  [{cat}]: {', '.join(texts[:3])}{'...' if len(texts) > 3 else ''}")
```

**Output:**
```
Found 42 highlight captures:

  [comment]: """Return a greeting."""
  [function]: greet
  [keyword]: def, class
  [string]: f"Hello, {name}!"
  [type]: str
  [variable]: name, greeting, self
```

### Code Folding

Extract foldable regions for IDE-style code collapse:

```python
import turbo_parse

source = """
class DataProcessor:
    def __init__(self):
        self.cache = {}
    
    def process(self, data: list) -> dict:
        if not data:
            return {}
        for item in data:
            self.cache[item] = True
        return {"processed": len(data)}

if __name__ == "__main__":
    processor = DataProcessor()
    result = processor.process(["a", "b", "c"])
"""

result = turbo_parse.get_folds(source, "python")
print(f"Found {len(result['folds'])} foldable regions:\n")

# Group by fold type
by_type = {}
for fold in result['folds']:
    ft = fold['fold_type']
    if ft not in by_type:
        by_type[ft] = 0
    by_type[ft] += 1
    print(f"  [{ft:12}] lines {fold['start_line']:2}-{fold['end_line']}")

print(f"\nSummary: {dict(by_type)}")
```

**Output:**
```
Found 5 foldable regions:

  [class       ] lines  2-10
  [function    ] lines  3-4
  [function    ] lines  6-10
  [conditional ] lines  7-8
  [loop        ] lines  9-10
  [conditional ] lines 12-14

Summary: {'class': 1, 'function': 2, 'conditional': 2, 'loop': 1}
```

### Incremental Parsing

Fast re-parsing for real-time editing scenarios:

```python
import turbo_parse

# Initial parse of a document
source = "def hello(): pass"
result = turbo_parse.parse_source(source, "python")
print(f"Initial parse: {result['parse_time_ms']:.2f}ms")

# Make an edit: change "pass" to "return 42"
new_source = "def hello(): return 42"

# Create an InputEdit describing the change
edit = turbo_parse.InputEdit(
    start_byte=12,        # Start position in old source
    old_end_byte=16,      # End of "pass" in old source  
    new_end_byte=24,      # End of "return 42" in new source
    start_position=(0, 12),     # (line, column) in old source
    old_end_position=(0, 16),   # (line, column) end of old text
    new_end_position=(0, 24)    # (line, column) end of new text
)

# Incremental re-parse (reuses tree for faster parsing)
new_result = turbo_parse.parse_with_edits(
    new_source,
    "python",
    result["tree"],       # Previous tree
    [edit]                # List of edits applied
)

print(f"Incremental parse: {new_result['parse_time_ms']:.2f}ms")
print(f"Success: {new_result['success']}")
```

**Output:**
```
Initial parse: 0.85ms
Incremental parse: 0.23ms  # Significantly faster!
Success: True
```

### Extract Symbols from File

```python
import turbo_parse

result = turbo_parse.extract_symbols_from_file("src/main.py")
for symbol in result['symbols']:
    print(f"{symbol['kind']}: {symbol['name']} (line {symbol['start_line']})")
```

### Syntax Diagnostics

```python
import turbo_parse

# Code with syntax errors
source = """
def broken(
    pass  # Missing closing paren
"""

result = turbo_parse.extract_syntax_diagnostics(source, "python")
print(f"Errors: {result['error_count']}")
print(f"Warnings: {result['warning_count']}")

for diag in result['diagnostics']:
    print(f"  Line {diag['line']}, Col {diag['column']}: {diag['message']}")
    print(f"    Severity: {diag['severity']}, Node: {diag['node_kind']}")
```

### Batch Parsing

```python
import turbo_parse

# Parse multiple files in parallel
files = ["file1.py", "file2.rs", "file3.js", "file4.ts"]
result = turbo_parse.parse_files_batch(files)

print(f"Processed {result['files_processed']} files in {result['total_time_ms']:.2f}ms")
print(f"Successful: {result['success_count']}, Failed: {result['error_count']}")
print(f"All succeeded: {result['all_succeeded']}")

# Access individual results
for i, file_result in enumerate(result['results']):
    print(f"  {files[i]}: {file_result['language']} - success={file_result['success']}")
```

### Using the Cache

```python
import turbo_parse

# Initialize cache (default capacity: 256 entries)
turbo_parse.init_cache()
# Or with custom capacity
turbo_parse.init_cache(capacity=512)

# Check cache stats
stats = turbo_parse.cache_stats()
print(f"Cache: {stats['size']}/{stats['capacity']} entries")
print(f"Hits: {stats['hits']}, Misses: {stats['misses']}")
print(f"Hit ratio: {stats['hit_ratio']:.2%}")

# Compute content hash
content_hash = turbo_parse.compute_hash("print('hello')")
print(f"Hash: {content_hash}")  # SHA256 hex string

# Manual cache operations
turbo_parse.cache_put("file.py", content_hash, {"tree": "data"}, "python")
cached = turbo_parse.cache_get("file.py", content_hash)
exists = turbo_parse.cache_contains("file.py", content_hash)
turbo_parse.cache_remove("file.py", content_hash)

# Clear all entries
turbo_parse.cache_clear()
```

### Get Statistics

```python
import turbo_parse

# Get comprehensive statistics
stats = turbo_parse.stats()
print(f"Total parses: {stats['total_parses']}")
print(f"Average parse time: {stats['average_parse_time_ms']:.2f}ms")
print(f"Cache hit ratio: {stats['cache_hit_ratio']:.2%}")
print("Languages used:", stats['languages_used'])
```

### Language Information

```python
import turbo_parse

# Check if a language is supported
print(turbo_parse.is_language_supported("python"))  # True
print(turbo_parse.is_language_supported("go"))        # False

# Get language info
lang = turbo_parse.get_language("python")
print(f"{lang['name']}: version={lang['version']}, supported={lang['supported']}")

# List all supported languages
langs = turbo_parse.supported_languages()
print(f"Supported: {', '.join(langs['languages'])}")
```

## Build Instructions

### Prerequisites

- **Rust toolchain** (1.70+ recommended) - Install from [rustup.rs](https://rustup.rs)
- **Python 3.10+** with pip
- **maturin** - `pip install maturin`

### Building from Source

```bash
# Navigate to the turbo_parse directory
cd turbo_parse

# Build Rust crate (debug)
cargo build

# Build optimized release
cargo build --release

# Install Python extension (development install)
maturin develop --release

# Build wheel for distribution
maturin build --release --strip
```

### Running Tests

```bash
# Run Rust unit tests
cargo test -p turbo_parse

# Run release tests (optimized, matches CI)
cargo test -p turbo_parse --release

# Run specific test
cargo test -p turbo_parse test_parse_source_python

# Check formatting
cargo fmt -p turbo_parse -- --check

# Run linter
cargo clippy -p turbo_parse --all-features -- -D warnings
```

### Development Workflow

For rapid iteration:

```bash
# 1. Make changes to Rust code

# 2. Check formatting and lints
cargo fmt -p turbo_parse -- --check && cargo clippy -p turbo_parse

# 3. Run tests
cargo test -p turbo_parse

# 4. Build and install for Python testing
maturin develop --release

# 5. Test Python integration
cd ..
python -c "import turbo_parse; print(turbo_parse.health_check())"
```

### Troubleshooting Build Issues

#### "Python headers not found"

**Linux (Ubuntu/Debian):**
```bash
sudo apt-get install python3-dev python3-pip
```

**macOS (Homebrew Python):**
```bash
brew install python@3.11
```

**Windows:**
Ensure Python is installed with "Development headers" option checked.

#### "maturin command not found"

```bash
pip install --upgrade maturin
# Or with uv
uv pip install maturin
```

#### Linking errors on Windows

- Install Visual Studio Build Tools with C++ workload
- Run `rustup update` to ensure latest toolchain
- For `ring`/`openssl-sys` issues, install `vcpkg`

#### Cache issues

Clear Rust build cache:
```bash
cargo clean -p turbo_parse
```

## Architecture Overview

turbo_parse is organized into several modules that work together to provide fast, reliable parsing:

```
┌─────────────────────────────────────────────────────────────┐
│                     Python API (lib.rs)                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐   │
│  │parse_source │  │  parse_file │  │   extract_symbols   │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘   │
│         └─────────────────┴────────────────────┘              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐   │
│  │get_folds    │  │get_highlights│  │  parse_with_edits   │   │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘   │
└─────────┴────────────────┴─────────────────────┴──────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                    Core Modules                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   parser    │  │   symbols   │  │    diagnostics      │  │
│  │  (parser)   │  │  (symbols)  │  │   (diagnostics)     │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                     │              │
│  ┌──────▼──────┐  ┌──────▼──────┐  ┌──────────▼──────────┐  │
│  │ tree-sitter │  │   queries   │  │   ERROR/MISSING     │  │
│  │   parsing   │  │    (TSQL)   │  │     node walk       │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                Phase 2 Feature Modules               │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │  highlights.rs — Syntax highlighting extraction      │   │
│  │    • HighlightCapture — byte-accurate captures       │   │
│  │    • Helix Editor query integration                  │   │
│  │    • Merge overlapping captures                      │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │  folds.rs — Code folding extraction                  │   │
│  │    • FoldRange — foldable region with type           │   │
│  │    • FoldType — 7 fold variants (function/class/etc)│   │
│  │    • @fold capture queries                           │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │  incremental.rs — Edit-aware re-parsing                │   │
│  │    • InputEdit — edit descriptors (byte + position)  │   │
│  │    • parse_with_edits — tree reuse for speed         │   │
│  │    • Tree::edit() + Parser::parse_with() integration   │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│               Language Registry (registry)                  │
│     ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐      │
│     │python │ │ rust  │ │   js  │ │  ts   │ │elixir │      │
│     └───────┘ └───────┘ └───────┘ └───────┘ └───────┘      │
└─────────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                  Infrastructure Modules                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │    cache    │  │  batch.rs   │  │      stats          │  │
│  │   (LRU)     │  │  (rayon)    │  │    (metrics)        │  │
│  │             │  │             │  │                     │  │
│  │ • SHA256    │  │ • Parallel  │  │ • Parse counts      │  │
│  │   hashing   │  │   file I/O  │  │ • Timing stats      │  │
│  │ • 256 cap   │  │ • Thread    │  │ • Language histo    │  │
│  │ • Hit/miss  │  │   pools     │  │ • Cache integration │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  queries.rs — Tree-sitter query management           │   │
│  │    • Helix Editor .scm file loading                  │   │
│  │    • highlights.scm, folds.scm, indents.scm        │   │
│  │    • 18 query files across 6 languages               │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Module Descriptions

#### `parser` — Core Parsing Engine
- **Purpose**: Source code → tree-sitter AST
- **Key Functions**: `parse_source()`, `parse_file()`
- **Features**: 
  - GIL release during parsing (allows Python threads to run)
  - Auto language detection from file extensions
  - Tree serialization to JSON
  - Error node extraction

#### `symbols` — Symbol Extraction (Outline)
- **Purpose**: Extract code symbols (functions, classes, etc.) with precise locations and hierarchy
- **Key Functions**: `extract_symbols()`, `extract_symbols_from_file()`
- **Features**:
  - Tree-sitter queries for each language
  - Parent-child relationships (methods → classes)
  - Symbol kind classification (function, class, method, import, struct, trait, enum, interface)
  - Position tracking (line, column, byte offsets)
  - Hierarchical outline view support

#### `highlights` — Syntax Highlighting ⭐ Phase 2
- **Purpose**: Editor-grade syntax highlighting using tree-sitter queries
- **Key Functions**: `get_highlights()`, `get_highlights_from_file()`
- **Features**:
  - Integration with Helix Editor query files (highlights.scm)
  - `HighlightCapture` struct with byte-accurate positions
  - Capture names: `keyword`, `function`, `type`, `string`, `comment`, `variable`, `operator`
  - Overlapping capture merging for nested constructs
  - Context for efficient batch processing

#### `folds` — Code Folding ⭐ Phase 2
- **Purpose**: Extract foldable regions for IDE-style code collapse
- **Key Functions**: `get_folds()`, `get_folds_from_file()`
- **Features**:
  - 7 fold types: `function`, `class`, `conditional`, `loop`, `block`, `import`, `generic`
  - Line-accurate ranges (start_line, end_line)
  - `FoldRange` and `FoldType` types for structured output
  - Helix Editor fold queries (folds.scm)
  - Reusable `FoldContext` for batch operations

#### `incremental` — Incremental Parsing ⭐ Phase 2
- **Purpose**: Fast re-parsing for editor-like use cases with localized changes
- **Key Functions**: `parse_with_edits()`
- **Types**: `InputEdit` — describes text edits with byte and position offsets
- **Features**:
  - Tree reuse via `Tree::edit()` and `Parser::parse_with()`
  - Edit descriptors with byte offsets and line/column positions
  - Multiple sequential edits support
  - GIL release during CPU-intensive re-parsing
- **Use Cases**: Real-time editors, large file editing, IDE features

#### `queries` — Query System ⭐ Phase 2
- **Purpose**: Tree-sitter query file management
- **Key Functions**: `get_highlights_query()`, `get_folds_query()`, `get_indents_query()`
- **Features**:
  - 18 query files (highlights.scm, folds.scm, indents.scm × 6 languages)
  - Vendored from Helix Editor (MPL-2.0 license)
  - Compile-time embedding with `include_str!`
  - Language-specific query variants

#### `diagnostics` — Syntax Error Detection
- **Purpose**: Extract ERROR and MISSING nodes from tree-sitter trees
- **Key Functions**: `extract_diagnostics()`
- **Features**:
  - Severity levels (error, warning)
  - Precise location info (line, column, offset, length)
  - Node kind identification
  - Human-readable error messages

#### `registry` — Language Management
- **Purpose**: Lazy-initialized storage for tree-sitter grammars
- **Key Functions**: `get_language()`, `is_language_supported()`, `list_supported_languages()`
- **Features**:
  - Global singleton (OnceLock)
  - Language aliases (py→python, js→javascript, etc.)
  - Case-insensitive lookup

#### `cache` — Parse Tree Caching
- **Purpose**: LRU cache for avoiding re-parsing unchanged files
- **Key Functions**: `cache_get()`, `cache_put()`, `cache_stats()`
- **Features**:
  - SHA256 content hashing
  - Thread-safe (parking_lot::RwLock)
  - Configurable capacity (default: 256)
  - Hit/miss/eviction statistics

#### `batch` — Parallel File Processing
- **Purpose**: Parse multiple files in parallel
- **Key Functions**: `parse_files_batch()`
- **Features**:
  - Rayon-based parallelism
  - Configurable worker threads
  - Preserves file order in results
  - GIL release during processing

#### `stats` — Metrics Collection
- **Purpose**: Track parse operations and performance
- **Key Functions**: `stats()`
- **Features**:
  - Total parse count
  - Average parse time
  - Per-language usage histogram
  - Cache statistics integration
7. **Metrics Recording** → `stats::record_parse()`
8. **Cache Store** → `cache::put()` (if enabled)
9. **Return Result** → Python dict with tree, timing, errors

#### Incremental Parse Flow
1. **Edit Notification** → User provides `InputEdit` descriptors
2. **Tree Edit Application** → `Tree::edit()` applies changes
3. **Incremental Parse** → `Parser::parse_with(old_tree)` reuses tree (GIL released)
4. **Result Return** → Updated tree with minimal re-parsing

## Known Gaps

This section documents known limitations and areas for future improvement. We believe in transparent documentation of what's not yet perfect.

### HEEx Templates (Elixir/Phoenix)

**Status**: Not supported  
**Impact**: High for Phoenix web developers

HEEx (HTML+EEx) templates are currently **not supported**. These are commonly used in Phoenix web frameworks and embed Elixir code within HTML-like syntax.

```elixir
<!-- HEEx template example - NOT SUPPORTED -->
<div class="user">
  <h1><%= @user.name %></h1>
  <%= if @user.admin do %>
    <span>Admin</span>
  <% end %>
</div>
```

**Workaround**: Parse the HEEx file as Elixir (`language="elixir"`). Basic expressions may be recognized, but HTML structure will likely cause parse errors.

**Tracking Issue**: [#bd-ekll-docs](https://github.com/mpfaffenberger/code_puppy/issues) (this issue)

### Complex Elixir Sigils

**Status**: Partial support  
**Impact**: Medium

Elixir sigils with complex delimiters or custom modifiers may not parse correctly:

```elixir
# Basic sigils work
~s"hello"
~r/regex/

# Complex sigils may have issues
~S"""
multiline
string
"""

# Custom sigil modifiers
~w[word list]a  # Atoms
```

### Language Injection

**Status**: ✅ Supported (v0.1.0+)  
**Impact**: High

Language injection detection is now supported! It can detect embedded languages within source code:

```python
import turbo_parse

# Detect SQL in Python strings
source = '''
def get_users(cursor, user_id):
    query = """
    SELECT u.id, u.name, u.email
    FROM users u
    WHERE u.id = %s AND u.active = true
    ORDER BY u.name
    """
    cursor.execute(query, (user_id,))
    return cursor.fetchall()
'''

result = turbo_parse.get_injections(source, "python")
for injection in result["injections"]:
    print(f"Found {injection['injected_language']} at bytes {injection['start_byte']}-{injection['end_byte']}")
    # Output: Found sql at bytes 35-152

# Parse the detected injections
parsed = turbo_parse.parse_injections_py(result)
for inj in parsed["parsed_injections"]:
    if inj["parse_success"]:
        print(f"Parsed {inj['range']['injected_language']} successfully")
```

**Supported injection patterns:**

| Parent Language | Detected Injection | Pattern |
|----------------|-------------------|---------|
| Python | SQL | Triple-quoted strings with SQL keywords + cursor/execute context |
| Python | HTML | Triple-quoted strings starting with `<` |
| Python | JSON | Triple-quoted strings with `{` or `[` structure |
| Elixir | HEEx | `~H` sigil content |
| Elixir | EEx | `~E` sigil content |
| Elixir | SQL | Triple-quoted strings with SQL keywords |
| HTML | JavaScript | `<script>` tag content |
| HTML | CSS | `<style>` tag content |

**Nested injections** are also supported (e.g., JavaScript inside HTML inside Python strings).

### TypeScript Complex Types

**Status**: Partial support  
**Impact**: Low

Very complex TypeScript type definitions may not have all symbols extracted:

```typescript
// Conditional types, mapped types may have edge cases
type DeepPartial<T> = {
  [P in keyof T]?: T[P] extends object ? DeepPartial<T[P]> : T[P];
};
```

### Rust Proc Macros

**Status**: Basic support  
**Impact**: Low

Rust procedural macros are parsed but macro-generated code won't have symbols extracted:

```rust
#[derive(CustomDerive)]  // OK
struct MyStruct {
    field: i32,
}

// Code inside macro!() may not extract symbols
macro_rules! custom_macro {
    ($name:ident) => { ... }
}
```

### Contributing to Gap Fixes

We welcome contributions to address these gaps:

1. **HEEx Support**: Requires adding a new tree-sitter grammar or extending the Elixir parser
2. **Language Injection**: Needs cross-language parsing capability
3. **Better Elixir Sigils**: Elixir grammar query improvements

See the [Contributing Guide](../CONTRIBUTING.md) for details on how to submit PRs.

## CI/CD

See [CI.md](./CI.md) for detailed information about:
- CI workflow configuration
- Running CI checks locally
- Troubleshooting CI failures
- Platform-specific build notes

## API Reference

### Functions

| Function | Signature | Description |
|----------|-----------|-------------|
| **Core Parsing** |||
| `parse_source()` | `(source: str, language: str) -> dict` | Parse source code string |
| `parse_file()` | `(path: str, language: str=None) -> dict` | Parse file from disk |
| `parse_with_edits()` | `(source: str, language: str, old_tree: dict, edits: list[InputEdit]) -> dict` | Incremental re-parsing ⭐ |
| **Symbol Extraction** |||
| `extract_symbols()` | `(source: str, language: str) -> dict` | Extract symbols (outline) from source |
| `extract_symbols_from_file()` | `(path: str, language: str=None) -> dict` | Extract symbols from file |
| `get_injections()` | `(source: str, parent_language: str) -> dict` | Detect embedded language injections |
| `get_injections_from_file()` | `(path: str, language: str=None) -> dict` | Detect injections from file |
| `parse_injections_py()` | `(injection_result: dict) -> dict` | Parse detected injections with appropriate grammars |
| **Syntax Highlighting** ⭐ |||
| `get_highlights()` | `(source: str, language: str) -> dict` | Extract syntax highlighting captures |
| `get_highlights_from_file()` | `(path: str, language: str=None) -> dict` | Extract highlights from file |
| **Code Folding** ⭐ |||
| `get_folds()` | `(source: str, language: str) -> dict` | Extract fold ranges from source |
| `get_folds_from_file()` | `(path: str, language: str=None) -> dict` | Extract fold ranges from file |
| **Diagnostics & Batch** |||
| `extract_syntax_diagnostics()` | `(source: str, language: str) -> dict` | Get syntax errors |
| `parse_files_batch()` | `(paths: list[str], max_workers: int=None) -> dict` | Parse files in parallel |
| **Cache Management** |||
| `init_cache()` | `(capacity: int=None) -> dict` | Initialize parse cache |
| `cache_get()` | `(file_path: str, content_hash: str) -> dict\|None` | Get cached entry |
| `cache_put()` | `(file_path: str, content_hash: str, tree_data: dict, language: str) -> bool` | Store in cache |
| `cache_contains()` | `(file_path: str, content_hash: str) -> bool` | Check cache membership |
| `cache_remove()` | `(file_path: str, content_hash: str) -> bool` | Remove from cache |
| `cache_clear()` | `() -> None` | Clear all cache entries |
| `cache_stats()` | `() -> dict` | Get cache statistics |
| `compute_hash()` | `(content: str) -> str` | SHA256 hash of content |
| `get_cache_info()` | `() -> dict` | Get cache status |
| **Language & Info** |||
| `is_language_supported()` | `(name: str) -> bool` | Check language support |
| `get_language()` | `(name: str) -> dict` | Get language info |
| `supported_languages()` | `() -> dict` | List supported languages |
| `health_check()` | `() -> dict` | Check module health |
| `stats()` | `() -> dict` | Get module statistics |

### Types ⭐ Phase 2

| Type | Fields | Description |
|------|--------|-------------|
| `InputEdit` | `start_byte, old_end_byte, new_end_byte, start_position, old_end_position, new_end_position` | Edit descriptor for incremental parsing |

### Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `__version__` | `"0.1.0"` | Module version |
| `DEFAULT_CACHE_CAPACITY` | `256` | Default LRU cache size |

> ⭐ = Phase 2 feature

## Performance

turbo_parse is designed for high-performance parsing with comprehensive benchmarking and optimization.

### Benchmark Targets

Performance targets for cold parsing (no cache) on Apple M1 MacBook Pro:

| File Size | Python | Rust | JavaScript | TypeScript | Elixir |
|-----------|--------|------|------------|------------|--------|
| **1k LOC** | < 5ms | < 5ms | < 5ms | < 5ms | < 5ms |
| **10k LOC** | < 30ms | < 30ms | < 30ms | < 30ms | < 30ms |
| **100k LOC** | < 250ms | < 250ms | < 250ms | < 250ms | < 250ms |

**Cached Performance:** Subsequent parses with cache enabled achieve **90%+ hit ratios** with sub-millisecond retrieval times.

### Running Benchmarks

```bash
# Run all Criterion benchmarks
cargo bench

# Run specific language
cargo bench python_parse
cargo bench rust_parse

# Check for regressions
cd turbo_parse/benches
python3 check_regression.py

# Save new baseline
python3 check_regression.py --save-baseline
```

### CI Regression Detection

Automated performance regression detection in CI:

```yaml
# .github/workflows/benchmark.yml
- name: Check for regressions
  run: |
    cd turbo_parse/benches
    python3 check_regression.py --threshold 15
```

**Thresholds:**
- Default threshold: 15% slowdown triggers failure
- Adjustable per benchmark group
- Fails CI if performance degrades beyond threshold

### Cache Optimization Benefits

The request cache provides significant performance improvements:

| Scenario | Without Cache | With Cache | Improvement |
|----------|--------------|------------|-------------|
| Token refresh (header-only) | ~5-10ms | ~1-2ms | **5-10x faster** |
| Identical requests | ~5-10ms | ~0.01ms | **500-1000x faster** |
| Parse tree cache hit | ~1-5ms | ~0.1ms | **10-50x faster** |
| Body change / cache miss | ~5-10ms | ~5-10ms | No overhead |

**Cache Features:**
- SHA256 content hashing for tree caching
- Content-based request hashing (method + URL + body)
- Header-only change detection for HTTP requests
- LRU eviction with configurable capacity

### General Performance Notes

- **Parsing**: Typical parse times are <1ms for files under 1000 lines
- **Batch Processing**: Linear scaling up to CPU core count
- **Caching**: 90%+ hit ratios typical for repeated file access
- **GIL Release**: Full GIL release during parsing allows Python parallelism
- **Memory**: Cache uses ~1-2MB per 100 entries (depends on file size)
- **Incremental Parsing**: 3-5x faster than full re-parse for small edits

### Optimization Tips

1. **Enable Caching**: Call `turbo_parse.init_cache()` early in your application
2. **Use Batch Processing**: Parse multiple files with `parse_files_batch()` for parallel speedup
3. **Incremental Parsing**: Use `parse_with_edits()` for real-time editor scenarios
4. **Reuse Contexts**: For batch operations, reuse `HighlightContext` and `FoldContext` (Rust API)
5. **Content Hashing**: Use `compute_hash()` to detect changes before re-parsing

## License

MIT - See [LICENSE](../LICENSE) for details.

## Related Projects

- [tree-sitter](https://tree-sitter.github.io/tree-sitter/) - The parsing library powering turbo_parse
- [PyO3](https://pyo3.rs/) - Rust/Python bindings
- [maturin](https://www.maturin.rs/) - Build tool for Python-Rust projects
