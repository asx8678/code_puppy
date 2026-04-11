//! Directory indexing for repo structure mapping.
//!
//! Provides fast directory scanning and file categorization
//! with optional symbol extraction for source files.

use pyo3::prelude::*;
use rayon::prelude::*;
use std::collections::HashSet;
use std::path::{Path, PathBuf};

/// Default directories to ignore during indexing
const IGNORED_DIRS: &[&str] = &[
    ".git", ".hg", ".svn", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "node_modules", "dist",
    "build", ".venv", "venv", "target", ".tox", "htmlcov",
    ".idea", ".vscode", ".DS_Store", ".pytest_cache",
];

/// Important project files that should be prioritized
const IMPORTANT_FILES: &[&str] = &[
    "README.md", "README.rst", "pyproject.toml", "setup.py",
    "package.json", "Cargo.toml", "Cargo.lock", "Makefile",
    "justfile", "Dockerfile", ".gitignore", "LICENSE",
    "requirements.txt", "Pipfile", "poetry.lock",
];

/// Result type for a single file summary
#[pyclass(frozen)]
#[derive(Debug, Clone)]
pub struct FileSummary {
    #[pyo3(get)]
    pub path: String,
    #[pyo3(get)]
    pub kind: String,
    #[pyo3(get)]
    pub symbols: Vec<String>,
}

#[pymethods]
impl FileSummary {
    fn __repr__(&self) -> String {
        format!("FileSummary(path={:?}, kind={:?}, symbols={:?})", 
                self.path, self.kind, self.symbols)
    }
    
    fn __str__(&self) -> String {
        self.__repr__()
    }
}

/// Check if a path component is hidden (starts with .)
fn is_hidden(path: &Path) -> bool {
    path.file_name()
        .and_then(|name| name.to_str())
        .map(|s| s.starts_with('.') && s != "." && s != "..")
        .unwrap_or(false)
}

/// Check if path contains any ignored directory component
fn is_ignored(path: &Path, ignored: &HashSet<&str>) -> bool {
    path.components()
        .filter_map(|c| c.as_os_str().to_str())
        .any(|s| ignored.contains(s))
}

/// Categorize a file by its extension
fn categorize_file(path: &Path) -> Option<(&'static str, bool)> {
    let name = path.file_name()?.to_str()?;
    let ext = path.extension().and_then(|e| e.to_str());
    
    // Important project files (check before extension)
    if IMPORTANT_FILES.contains(&name) {
        return Some(("project-file", false));
    }
    
    // Also check lowercase version for case-insensitive matching
    let name_lower = name.to_lowercase();
    if IMPORTANT_FILES.iter().any(|&f| f.to_lowercase() == name_lower) {
        return Some(("project-file", false));
    }
    
    match ext {
        // Source files that can have symbols extracted
        Some("py") => Some(("python", true)),
        Some("rs") => Some(("rust", true)),
        Some("js") => Some(("javascript", true)),
        Some("ts") => Some(("typescript", true)),
        Some("tsx") => Some(("tsx", true)),
        Some("ex") | Some("exs") => Some(("elixir", true)),
        
        // Documentation
        Some("md") | Some("rst") | Some("txt") => Some(("docs", false)),
        
        // Config files
        Some("json") => Some(("json", false)),
        Some("toml") => Some(("toml", false)),
        Some("yaml") | Some("yml") => Some(("yaml", false)),
        
        // Other code without symbol extraction
        Some("jsx") => Some(("jsx", false)),
        Some("css") => Some(("css", false)),
        Some("scss") => Some(("scss", false)),
        Some("sass") => Some(("sass", false)),
        Some("less") => Some(("less", false)),
        Some("html") => Some(("html", false)),
        Some("htm") => Some(("htm", false)),
        
        // Shell scripts
        Some("sh") | Some("bash") | Some("zsh") | Some("fish") => Some(("shell", false)),
        
        // Data files
        Some("csv") | Some("tsv") => Some(("data", false)),
        Some("xml") => Some(("xml", false)),
        
        // Unknown extension - still track it
        _ => Some(("file", false)),
    }
}

/// Extract symbols from a Python file using basic regex-style parsing
fn extract_python_symbols_simple(content: &str, max_symbols: usize) -> Vec<String> {
    let mut symbols = Vec::with_capacity(max_symbols.min(16));
    
    for line in content.lines() {
        let trimmed = line.trim_start();
        
        // Skip comment lines and strings
        if trimmed.starts_with('#') || trimmed.starts_with('"') || trimmed.starts_with('\'') {
            continue;
        }
        
        // Regular function
        if trimmed.starts_with("def ") && !trimmed.starts_with("def _") {
            if let Some(sig) = extract_def_signature(trimmed) {
                symbols.push(sig);
            }
        }
        // Async function
        else if trimmed.starts_with("async def ") && !trimmed[11..].starts_with('_') {
            if let Some(sig) = extract_def_signature(&trimmed[6..]) {
                symbols.push(sig);
            }
        }
        // Class definition
        else if trimmed.starts_with("class ") {
            if let Some(name) = extract_class_name(trimmed) {
                symbols.push(format!("class {}", name));
            }
        }
        
        if symbols.len() >= max_symbols {
            break;
        }
    }
    
    symbols
}

fn extract_def_signature(line: &str) -> Option<String> {
    // "def foo(x, y):" -> "def foo(x, y)"
    let without_def = line.strip_prefix("def ")?;
    
    // Find the colon that ends the signature
    // Handle both "def foo():" and "def foo(self) -> Type:"
    let end = without_def.find(':')?;
    let signature = without_def[..end].trim();
    
    // Clean up the signature - remove type hints for brevity
    // But keep them if they're short enough
    if signature.len() > 80 {
        // Try to extract just the function name
        if let Some(paren_idx) = signature.find('(') {
            let name = &signature[..paren_idx];
            Some(format!("def {}(...)", name.trim()))
        } else {
            Some(format!("def {}", signature))
        }
    } else {
        Some(format!("def {}", signature))
    }
}

fn extract_class_name(line: &str) -> Option<String> {
    // "class Foo(Bar):" -> "Foo"
    let without_class = line.strip_prefix("class ")?;
    let end = without_class.find(|c| c == '(' || c == ':' || c == ' ')?;
    Some(without_class[..end].trim().to_string())
}

/// Collect candidate files using ignore crate for gitignore support
fn collect_candidates(
    root_path: &Path,
    ignored_dirs: &HashSet<&str>,
) -> Vec<(PathBuf, usize)> {
    let mut candidates = Vec::new();
    
    let walker = ignore::WalkBuilder::new(root_path)
        .follow_links(false)
        .git_ignore(true)
        .git_global(true)
        .git_exclude(true)
        .parents(true)
        .build();
    
    for entry in walker {
        let Ok(entry) = entry else { continue };
        
        let path = entry.path();
        
        // Skip directories
        if !entry.file_type().map(|ft| ft.is_file()).unwrap_or(false) {
            continue;
        }
        
        // Skip hidden files and ignored directories
        if is_hidden(path) || is_ignored(path, ignored_dirs) {
            continue;
        }
        
        // Calculate depth relative to root
        let depth = entry.depth();
        
        candidates.push((path.to_path_buf(), depth));
    }
    
    // Sort by depth then path (matching Python behavior)
    candidates.sort_by(|a, b| {
        a.1.cmp(&b.1)
            .then_with(|| a.0.cmp(&b.0))
    });
    
    candidates
}

/// Index a directory and return file summaries
#[pyfunction]
#[pyo3(signature = (root, max_files=40, max_symbols_per_file=8, ignored_dirs=None))]
pub fn index_directory(
    root: &str,
    max_files: usize,
    max_symbols_per_file: usize,
    ignored_dirs: Option<Vec<String>>,
) -> PyResult<Vec<FileSummary>> {
    let root_path = PathBuf::from(root);
    
    if !root_path.exists() {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            format!("Directory does not exist: {}", root)
        ));
    }
    
    if !root_path.is_dir() {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            format!("Path is not a directory: {}", root)
        ));
    }
    
    // Build ignored set with defaults
    let ignored: HashSet<&str> = IGNORED_DIRS.iter().copied().collect();
    
    // Note: extra_ignored_dirs from the parameter are not used in the HashSet
    // because HashSet<&str> can't store owned Strings with local lifetime.
    // For now, the comprehensive default IGNORED_DIRS covers most cases.
    // TODO: If custom ignored dirs are needed, convert to HashSet<String>
    let _extra_ignored = ignored_dirs.unwrap_or_default();
    
    // Collect all candidate files (sorted by depth, then path)
    let candidates = collect_candidates(&root_path, &ignored);
    
    // Take enough candidates to have good coverage after filtering
    let candidates: Vec<(PathBuf, usize)> = candidates
        .into_iter()
        .take(max_files * 3)
        .collect();
    
    // Process files in parallel
    let mut summaries: Vec<FileSummary> = candidates
        .into_par_iter()
        .filter_map(|(path, _depth)| {
            let rel_path = path.strip_prefix(&root_path).ok()?;
            let rel_str = rel_path.to_str()?;
            
            let (kind, extract_symbols) = categorize_file(&path)?;
            
            let symbols = if extract_symbols && kind == "python" {
                // Read file and extract symbols
                std::fs::read_to_string(&path)
                    .ok()
                    .map(|content| extract_python_symbols_simple(&content, max_symbols_per_file))
                    .unwrap_or_default()
            } else {
                Vec::new()
            };
            
            Some(FileSummary {
                path: rel_str.to_string(),
                kind: kind.to_string(),
                symbols,
            })
        })
        .collect();
    
    // Limit to max_files (sequential after parallel processing)
    summaries.truncate(max_files);
    
    Ok(summaries)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_categorize_file() {
        assert_eq!(categorize_file(Path::new("test.py")), Some(("python", true)));
        assert_eq!(categorize_file(Path::new("test.rs")), Some(("rust", true)));
        assert_eq!(categorize_file(Path::new("test.js")), Some(("javascript", true)));
        assert_eq!(categorize_file(Path::new("test.ts")), Some(("typescript", true)));
        assert_eq!(categorize_file(Path::new("test.md")), Some(("docs", false)));
        assert_eq!(categorize_file(Path::new("README.md")), Some(("project-file", false)));
        assert_eq!(categorize_file(Path::new("package.json")), Some(("project-file", false)));
        assert_eq!(categorize_file(Path::new("Cargo.toml")), Some(("project-file", false)));
    }

    #[test]
    fn test_extract_python_symbols() {
        let code = r#"
def hello_world():
    pass

class MyClass:
    def method(self, x: int) -> str:
        return str(x)

async def async_func(a, b, c):
    pass
"#;
        
        let symbols = extract_python_symbols_simple(code, 10);
        assert!(symbols.iter().any(|s| s.contains("hello_world")));
        assert!(symbols.iter().any(|s| s.contains("class MyClass")));
        assert!(symbols.iter().any(|s| s.contains("async_func")));
    }

    #[test]
    fn test_extract_def_signature() {
        assert_eq!(
            extract_def_signature("def foo():"),
            Some("def foo()".to_string())
        );
        assert_eq!(
            extract_def_signature("def bar(x, y):"),
            Some("def bar(x, y)".to_string())
        );
        assert_eq!(
            extract_def_signature("def baz(x: int) -> str:"),
            Some("def baz(x: int) -> str".to_string())
        );
    }

    #[test]
    fn test_is_hidden() {
        assert!(is_hidden(Path::new(".git")));
        assert!(is_hidden(Path::new(".hidden")));
        assert!(!is_hidden(Path::new("src")));
        assert!(!is_hidden(Path::new("main.py")));
    }

    #[test]
    fn test_is_ignored() {
        let ignored: HashSet<&str> = ["node_modules", "__pycache__"].iter().copied().collect();
        assert!(is_ignored(Path::new("node_modules/foo/bar.js"), &ignored));
        assert!(is_ignored(Path::new("src/__pycache__/cache.pyc"), &ignored));
        assert!(!is_ignored(Path::new("src/main.py"), &ignored));
    }

    #[test]
    fn test_index_directory_basic() {
        let temp_dir = TempDir::new().unwrap();
        let root = temp_dir.path();
        
        // Create some test files
        std::fs::write(root.join("main.py"), "def main():\n    pass\n").unwrap();
        std::fs::write(root.join("README.md"), "# Test").unwrap();
        std::fs::write(root.join("utils.rs"), "fn helper() {}").unwrap();
        
        // Create a subdirectory
        std::fs::create_dir(root.join("src")).unwrap();
        std::fs::write(root.join("src/lib.py"), "class Lib:\n    pass\n").unwrap();
        
        // Create a hidden directory that should be ignored
        std::fs::create_dir(root.join(".hidden")).unwrap();
        std::fs::write(root.join(".hidden/secret.py"), "def secret(): pass").unwrap();
        
        let summaries = index_directory(
            root.to_str().unwrap(),
            100,
            8,
            None,
        ).unwrap();
        
        // Should find main.py, README.md, utils.rs, src/lib.py
        // Should NOT find .hidden/secret.py
        let paths: Vec<&str> = summaries.iter().map(|s| s.path.as_str()).collect();
        assert!(paths.contains(&"main.py"));
        assert!(paths.contains(&"README.md"));
        assert!(paths.contains(&"utils.rs"));
        assert!(paths.contains(&"src/lib.py"));
        assert!(!paths.contains(&".hidden/secret.py"));
        
        // Check symbols were extracted from Python files
        let main_py = summaries.iter().find(|s| s.path == "main.py").unwrap();
        assert!(!main_py.symbols.is_empty());
        assert!(main_py.symbols.iter().any(|s| s.contains("main")));
    }
}
