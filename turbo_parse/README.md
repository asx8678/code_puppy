# turbo_parse

[![CI](https://github.com/mpfaffenberger/code_puppy/actions/workflows/turbo_parse.yml/badge.svg)](https://github.com/mpfaffenberger/code_puppy/actions/workflows/turbo_parse.yml)
[![Crates.io](https://img.shields.io/badge/Rust-turbo_parse-orange?logo=rust)](https://github.com/mpfaffenberger/code_puppy/tree/main/turbo_parse)
[![Python Versions](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue?logo=python)](https://pypi.org/project/turbo-parse/)
[![Platforms](https://img.shields.io/badge/platforms-linux%20|%20macos%20|%20windows-lightgrey)](./CI.md)

High-performance parsing with tree-sitter and PyO3 bindings for Code Puppy.

## Features

- **Blazing Fast**: Rust-powered parsing with tree-sitter, GIL release during CPU-intensive operations
- **Multi-Language**: Support for Python, Rust, JavaScript, TypeScript, TSX, and Elixir
- **Symbol Extraction**: Extract functions, classes, methods, imports with precise location info
- **Diagnostics**: Syntax error detection with detailed position information
- **Caching**: LRU cache for parsed trees to avoid re-parsing unchanged files
- **Incremental Parsing**: Fast re-parsing with tree reuse for editor-like use cases
- **Batch Processing**: Parallel file parsing across all CPU cores
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

### Extract Symbols

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
print(f"Found {len(result['symbols'])} symbols:")

for symbol in result['symbols']:
    kind = symbol['kind']
    name = symbol['name']
    line = symbol['start_line']
    parent = symbol.get('parent', None)
    
    if parent:
        print(f"  [{kind}] {name} (line {line}) - in {parent}")
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
  [method] process (line 12) - in DataProcessor
```

### Extract Symbols from File

```python
import turbo_parse

result = turbo_parse.extract_symbols_from_file("src/main.py")
for symbol in result['symbols']:
    print(f"{symbol['kind']}: {symbol['name']} (line {symbol['start_line']})")
```

### Syntax Highlighting

Extract syntax highlighting captures from source code using tree-sitter queries.

```python
import turbo_parse

source = """
def greet(name: str) -> str:
    # Return a greeting
    return f"Hello, {name}!"

class Greeter:
    DEFAULT_GREETING = "Hi"
    
    def __init__(self, greeting: str = None):
        self.greeting = greeting or self.DEFAULT_GREETING
"""

result = turbo_parse.get_highlights(source, "python")
print(f"Found {len(result['captures'])} highlight captures:")

for capture in result['captures']:
    name = capture['capture_name']
    start = capture['start_byte']
    end = capture['end_byte']
    text = source[start:end]
    print(f"  [{name}] bytes {start}-{end}: '{text[:30]}...'")
```

**Output:**
```
Found 37 highlight captures:
  [keyword] bytes 1-4: 'def'
  [function] bytes 5-10: 'greet'
  [variable] bytes 25-27: 'str'
  [comment] bytes 34-54: '# Return a greeting'
  [string] bytes 68-83: 'Hello, {name}!'
  [keyword] bytes 87-92: 'class'
  [type] bytes 93-100: 'Greeter'
  ...
```

**Common Capture Names:**
- `keyword` - Keywords (def, class, if, return, etc.)
- `function` - Function definitions
- `type` - Type names
- `string` - String literals
- `comment` - Comments
- `variable` - Variables
- `constant` - Constants
- `operator` - Operators
- `punctuation` - Brackets, delimiters

### Extract Folds (Code Folding)

```python
import turbo_parse

source = """
def hello(name: str) -> str:
    return f"Hello, {name}!"

class DataProcessor:
    def __init__(self):
        self.cache = {}
    
    def process(self, data: List[str]) -> dict:
        return process_data(data)
        
    if True:
        print("conditional block")
"""

result = turbo_parse.get_folds(source, "python")
print(f"Found {len(result['folds'])} foldable regions:")

for fold in result['folds']:
    fold_type = fold['fold_type']
    start = fold['start_line']
    end = fold['end_line']
    print(f"  [{fold_type}] lines {start}-{end}")
```

**Output:**
```
Found 4 foldable regions:
  [function] lines 2-3
  [class] lines 5-12
  [function] lines 7-8
  [function] lines 10-11
  [conditional] lines 13-14
```

**Fold Types:**
- `function` - Function definitions
- `class` - Class/struct definitions
- `conditional` - If statements, match expressions, switch statements
- `loop` - For, while, loop constructs
- `block` - Try blocks, with statements, impl blocks
- `import` - Import/export statements
- `generic` - Generic blocks (objects, arrays, JSX elements)

### Extract Folds from File

```python
import turbo_parse

result = turbo_parse.get_folds_from_file("src/main.py")
for fold in result['folds']:
    print(f"{fold['fold_type']}: lines {fold['start_line']}-{fold['end_line']}")
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

### Incremental Parsing

For editor-like scenarios where small edits are made to existing documents,
turbo_parse supports incremental parsing. This reuses the previous parse tree
and applies text edits, resulting in significantly faster re-parsing for small
changes.

**When to use incremental parsing:**
- Real-time editor scenarios (typing, small edits)
- Large files with localized changes
- IDE features requiring frequent re-parsing

**When NOT to use incremental parsing:**
- Initial parse of a document
- Massive structural changes (better to do full re-parse)
- When you don't have access to the previous parse tree

```python
import turbo_parse

# Initial parse of a document
source = "def hello(): pass"
result = turbo_parse.parse_source(source, "python")

# Make an edit: change "pass" to "return 42"
new_source = "def hello(): return 42"

# Create an InputEdit describing the change
# The edit describes what changed between old and new source
edit = turbo_parse.InputEdit(
    start_byte=12,        # Start position in old source
    old_end_byte=16,      # End of "pass" in old source
    new_end_byte=21,      # End of "return 42" in new source
    start_position=(0, 12),     # (line, column) in old source
    old_end_position=(0, 16),     # (line, column) end of old text
    new_end_position=(0, 21)      # (line, column) end of new text
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
print(f"Tree updated incrementally")
```

**InputEdit fields:**
- `start_byte` - Byte offset where edit starts in old document
- `old_end_byte` - Byte offset where replaced region ended in old document
- `new_end_byte` - Byte offset where new text ends in new document
- `start_position` - (line, column) tuple where edit starts (0-indexed)
- `old_end_position` - (line, column) where old text ended
- `new_end_position` - (line, column) where new text ends

**Multiple edits:**
You can apply multiple sequential edits in a single incremental parse:

```python
edits = [
    turbo_parse.InputEdit(0, 0, 5, (0, 0), (0, 0), (0, 5)),     # Insert at start
    turbo_parse.InputEdit(10, 15, 20, (0, 10), (0, 15), (0, 20)), # Replace middle
]
result = turbo_parse.parse_with_edits(new_source, "python", old_tree, edits)
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

turbo_parse is organized into several modules that work together:

```
┌─────────────────────────────────────────────────────────────┐
│                     Python API (lib.rs)                     │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐   │
│  │parse_source │  │  parse_file │  │   extract_symbols   │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘   │
│         └─────────────────┴────────────────────┘              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐   │
│  │  get_folds  │  │ get_folds_  │  │ extract_symbols_    │   │
│  │             │  │ from_file   │  │ from_file           │   │
│  └─────────────┴──┴─────────────┴──┴─────────────────────┘   │
└─────────────────────────┬───────────────────────────────────┘
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
│  │                  incremental.rs                      │   │
│  │  • InputEdit struct — edit descriptors               │   │
│  │  • parse_with_edits — incremental re-parsing         │   │
│  │  • Tree::edit() + Parser::parse_with() integration    │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                    folds.rs                          │   │
│  │  • FoldRange struct — foldable regions               │   │
│  │  • FoldType enum — function, class, block, etc.       │   │
│  │  • FoldContext — reusable query state               │   │
│  │  • @fold capture queries from Helix Editor          │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│               Language Registry (registry)                    │
│     ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐      │
│     │python │ │ rust  │ │   js  │ │  ts   │ │elixir │      │
│     └───────┘ └───────┘ └───────┘ └───────┘ └───────┘      │
└─────────────────────────────────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│                  Infrastructure Modules                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │    cache    │  │  batch.rs   │  │      stats          │  │
│  │   (LRU)     │  │  (rayon)    │  │    (metrics)        │  │
│  │             │  │             │  │                     │  │
│  │ • SHA256    │  │ • Parallel  │  │ • Parse counts      │  │
│  │   hashing   │  │   file I/O  │  │ • Timing stats      │  │
│  │ • 256 cap   │  │ • Thread    │  │ • Language histo    │  │
│  │ • Hit/miss  │  │   pools     │  │ • Cache integration │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
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

#### `symbols` — Symbol Extraction
- **Purpose**: Extract code symbols (functions, classes, etc.) with precise locations
- **Key Functions**: `extract_symbols()`, `extract_symbols_from_file()`
- **Features**:
  - Tree-sitter queries for each language
  - Parent-child relationships (methods → classes)
  - Symbol kind classification (function, class, method, import, etc.)
  - Position tracking (line, column, byte offsets)

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

#### `incremental` — Incremental Parsing
- **Purpose**: Fast re-parsing for editor-like use cases with localized changes
- **Key Functions**: `parse_with_edits()`
- **Types**: `InputEdit` — describes text edits with byte and position offsets
- **Features**:
  - Tree reuse via `Tree::edit()` and `Parser::parse_with()`
  - Edit descriptors with byte offsets and line/column positions
  - Multiple sequential edits support
  - GIL release during CPU-intensive re-parsing
- **Use Cases**: Real-time editors, large file editing, IDE features

### Data Flow

#### Standard Parse Flow
1. **Parse Request** → `parse_source()` or `parse_file()`
2. **Language Detection** → `registry::get_language()`
3. **Cache Check** → `cache::get()` (if enabled)
4. **Tree-sitter Parse** → Creates AST (GIL released)
5. **Tree Serialization** → JSON representation
6. **Diagnostics Extraction** → ERROR/MISSING nodes
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

**Status**: Not supported  
**Impact**: Medium

Embedded languages (language injection) are not yet supported:

```python
# SQL within Python string - not recognized as SQL
query = """
SELECT * FROM users WHERE id = %s
"""
```

```javascript
// CSS within styled-components - not recognized as CSS
const Button = styled.button`
  background: blue;
  color: white;
`;
```

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
| `health_check()` | `() -> dict` | Check module health and get version info |
| `parse_source()` | `(source: str, language: str) -> dict` | Parse source code string |
| `parse_file()` | `(path: str, language: str=None) -> dict` | Parse file from disk |
| `extract_symbols()` | `(source: str, language: str) -> dict` | Extract symbols from source |
| `extract_symbols_from_file()` | `(path: str, language: str=None) -> dict` | Extract symbols from file |
| `get_folds()` | `(source: str, language: str) -> dict` | Extract fold ranges from source |
| `get_folds_from_file()` | `(path: str, language: str=None) -> dict` | Extract fold ranges from file |
| `get_highlights()` | `(source: str, language: str) -> dict` | Extract syntax highlighting captures |
| `get_highlights_from_file()` | `(path: str, language: str=None) -> dict` | Extract highlights from file |
| `extract_syntax_diagnostics()` | `(source: str, language: str) -> dict` | Get syntax errors |
| `parse_files_batch()` | `(paths: list[str], max_workers: int=None) -> dict` | Parse files in parallel |
| `init_cache()` | `(capacity: int=None) -> dict` | Initialize parse cache |
| `cache_get()` | `(file_path: str, content_hash: str) -> dict\|None` | Get cached entry |
| `cache_put()` | `(file_path: str, content_hash: str, tree_data: dict, language: str) -> bool` | Store in cache |
| `cache_contains()` | `(file_path: str, content_hash: str) -> bool` | Check cache membership |
| `cache_remove()` | `(file_path: str, content_hash: str) -> bool` | Remove from cache |
| `cache_clear()` | `() -> None` | Clear all cache entries |
| `cache_stats()` | `() -> dict` | Get cache statistics |
| `compute_hash()` | `(content: str) -> str` | SHA256 hash of content |
| `get_cache_info()` | `() -> dict` | Get cache status |
| `is_language_supported()` | `(name: str) -> bool` | Check language support |
| `get_language()` | `(name: str) -> dict` | Get language info |
| `supported_languages()` | `() -> dict` | List supported languages |
| `stats()` | `() -> dict` | Get module statistics |

### Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `__version__` | `"0.1.0"` | Module version |
| `DEFAULT_CACHE_CAPACITY` | `256` | Default LRU cache size |

## Performance Notes

- **Parsing**: Typical parse times are <1ms for files under 1000 lines
- **Batch Processing**: Linear scaling up to CPU core count
- **Caching**: 90%+ hit ratios typical for repeated file access
- **GIL Release**: Full GIL release during parsing allows Python parallelism
- **Memory**: Cache uses ~1-2MB per 100 entries (depends on file size)

## License

MIT - See [LICENSE](../LICENSE) for details.

## Related Projects

- [tree-sitter](https://tree-sitter.github.io/tree-sitter/) - The parsing library powering turbo_parse
- [PyO3](https://pyo3.rs/) - Rust/Python bindings
- [maturin](https://www.maturin.rs/) - Build tool for Python-Rust projects
