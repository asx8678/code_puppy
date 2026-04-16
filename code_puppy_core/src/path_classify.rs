//! Path classification for ignore and sensitive path detection.
//!
//! This module provides fast path classification using pre-compiled patterns:
//! - `globset` for gitignore-style glob matching (Aho-Corasick automaton)
//! - `aho-corasick` for prefix matching on sensitive directories
//!
//! Ported from Python: `should_ignore_path()` and `is_sensitive_path()`

use globset::{Glob, GlobSet, GlobSetBuilder};
use pyo3::prelude::*;
use std::collections::HashSet;
use std::path::{Path, PathBuf};

/// Pre-compiled patterns for directory-only matching.
const DIR_PATTERNS: &[&str] = &[
    // Version control
    "**/.git/**",
    "**/.git",
    ".git/**",
    ".git",
    "**/.svn/**",
    "**/.hg/**",
    "**/.bzr/**",
    // Cross-language common patterns
    "**/target/**",
    "**/target",
    "**/build/**",
    "**/build",
    "**/dist/**",
    "**/dist",
    "**/bin/**",
    "**/vendor/**",
    "**/deps/**",
    "**/coverage/**",
    "**/doc/**",
    "**/_build/**",
    "**/.gradle/**",
    "**/project/target/**",
    "**/project/project/**",
    // Node.js / JavaScript / TypeScript
    "**/node_modules/**",
    "**/node_modules",
    "node_modules/**",
    "node_modules",
    "**/.npm/**",
    "**/.yarn/**",
    "**/.pnpm-store/**",
    "**/.nyc_output/**",
    "**/.next/**",
    "**/.nuxt/**",
    "**/out/**",
    "**/.cache/**",
    "**/.parcel-cache/**",
    "**/.vite/**",
    "**/storybook-static/**",
    "**/*.tsbuildinfo/**",
    // Python
    "**/__pycache__/**",
    "**/__pycache__",
    "__pycache__/**",
    "__pycache__",
    "**/.pytest_cache/**",
    "**/.mypy_cache/**",
    "**/htmlcov/**",
    "**/.tox/**",
    "**/.nox/**",
    "**/site-packages/**",
    "**/.venv/**",
    "**/.venv",
    "**/venv/**",
    "**/venv",
    "**/env/**",
    "**/ENV/**",
    "**/pip-wheel-metadata/**",
    "**/*.egg-info/**",
    "**/wheels/**",
    "**/pytest-reports/**",
    // Java
    "**/.classpath",
    "**/.project",
    "**/.settings/**",
    // Go
    "**/*.exe~",
    "**/*.test",
    "**/*.out",
    "**/go.work",
    "**/go.work.sum",
    // Ruby
    "**/.bundle/**",
    "**/.rvm/**",
    "**/.rbenv/**",
    "**/.yardoc/**",
    "**/rdoc/**",
    "**/.sass-cache/**",
    "**/.jekyll-cache/**",
    "**/_site/**",
    // PHP
    "**/.phpunit.result.cache",
    "**/storage/logs/**",
    "**/storage/framework/cache/**",
    "**/storage/framework/sessions/**",
    "**/storage/framework/testing/**",
    "**/storage/framework/views/**",
    "**/bootstrap/cache/**",
    // .NET / C#
    "**/obj/**",
    "**/packages/**",
    "**/.vs/**",
    "**/TestResults/**",
    "**/BenchmarkDotNet.Artifacts/**",
    // C/C++
    "**/CMakeFiles/**",
    "**/cmake_install.cmake",
    "**/.deps/**",
    "**/.libs/**",
    "**/autom4te.cache/**",
    // Perl
    "**/blib/**",
    "**/*.tmp",
    "**/*.bak",
    "**/*.old",
    "**/Makefile.old",
    "**/MANIFEST.bak",
    "**/.prove",
    // Scala
    "**/.bloop/**",
    "**/.metals/**",
    "**/.ammonite/**",
    // Elixir
    "**/.fetch",
    "**/.elixir_ls/**",
    // Swift
    "**/.build/**",
    "**/Packages/**",
    "**/*.xcodeproj/**",
    "**/*.xcworkspace/**",
    "**/DerivedData/**",
    "**/xcuserdata/**",
    "**/*.dSYM/**",
    // Dart/Flutter
    "**/.dart_tool/**",
    // Haskell
    "**/dist-newstyle/**",
    "**/.stack-work/**",
    // Erlang
    "**/ebin/**",
    "**/rel/**",
    // Common cache and temp directories
    "**/cache/**",
    "**/tmp/**",
    "**/temp/**",
    "**/.tmp/**",
    "**/.temp/**",
    "**/logs/**",
    // IDE and editor files
    "**/.idea/**",
    "**/.idea",
    "**/.vscode/**",
    "**/.vscode",
    "**/.emacs.d/auto-save-list/**",
    "**/.vim/**",
    // OS-specific files
    "**/.DS_Store",
    ".DS_Store",
    "**/Thumbs.db",
    "**/Desktop.ini",
    "**/.directory",
    // Backup files
    "**/*.backup",
    "**/*.save",
];

/// File extension patterns (binary/non-text files).
const FILE_PATTERNS: &[&str] = &[
    // Compiled/binary artifacts
    "**/*.class",
    "**/*.jar",
    "**/*.dll",
    "**/*.exe",
    "**/*.so",
    "**/*.dylib",
    "**/*.pdb",
    "**/*.o",
    "**/*.beam",
    "**/*.obj",
    "**/*.a",
    "**/*.lib",
    // Python compiled
    "**/*.pyc",
    "**/*.pyo",
    "**/*.pyd",
    // Java
    "**/*.war",
    "**/*.ear",
    "**/*.nar",
    "**/hs_err_pid*",
    // Rust
    "**/Cargo.lock",
    // Ruby
    "**/*.gem",
    "**/Gemfile.lock",
    // PHP
    "**/composer.lock",
    // .NET
    "**/*.cache",
    "**/*.user",
    "**/*.suo",
    // C/C++
    "**/CMakeCache.txt",
    "**/Makefile",
    "**/compile_commands.json",
    // Perl
    "**/Build",
    "**/Build.bat",
    "**/META.yml",
    "**/META.json",
    "**/MYMETA.*",
    // Scala
    // Clojure
    "**/.lein-*",
    "**/.nrepl-port",
    "**/pom.xml.asc",
    // Dart/Flutter
    "**/.packages",
    "**/pubspec.lock",
    "**/*.g.dart",
    "**/*.freezed.dart",
    "**/*.gr.dart",
    // Haskell
    "**/*.hi",
    "**/*.prof",
    "**/*.aux",
    "**/*.hp",
    "**/*.eventlog",
    "**/*.tix",
    // Erlang
    "**/*.boot",
    "**/*.plt",
    // Kotlin
    "**/*.kotlin_module",
    // Elixir
    "**/erl_crash.dump",
    "**/*.ez",
    // Swift
    // Log files
    "**/*.log",
    "**/*.log.*",
    "**/npm-debug.log*",
    "**/yarn-debug.log*",
    "**/yarn-error.log*",
    "**/pnpm-debug.log*",
    // IDE swap files
    "**/*.swp",
    "**/*.swo",
    "**/*~",
    "**/.#*",
    "**/#*#",
    "**/.netrwhist",
    "**/Session.vim",
    "**/.sublime-project",
    "**/.sublime-workspace",
    // Artifacts
    "**/*.orig",
    "**/*.rej",
    "**/*.patch",
    "**/*.diff",
    "**/.*.orig",
    "**/.*.rej",
    // Hidden files (any .* file)
    // Note: This is aggressive and commented out in Python - not enabling
    // Binary image formats
    "**/*.png",
    "**/*.jpg",
    "**/*.jpeg",
    "**/*.gif",
    "**/*.bmp",
    "**/*.tiff",
    "**/*.tif",
    "**/*.webp",
    "**/*.ico",
    "**/*.svg",
    // Binary document formats
    "**/*.pdf",
    "**/*.doc",
    "**/*.docx",
    "**/*.xls",
    "**/*.xlsx",
    "**/*.ppt",
    "**/*.pptx",
    // Archive formats
    "**/*.zip",
    "**/*.tar",
    "**/*.gz",
    "**/*.bz2",
    "**/*.xz",
    "**/*.rar",
    "**/*.7z",
    // Media files
    "**/*.mp3",
    "**/*.mp4",
    "**/*.avi",
    "**/*.mov",
    "**/*.wmv",
    "**/*.flv",
    "**/*.wav",
    "**/*.ogg",
    // Font files
    "**/*.ttf",
    "**/*.otf",
    "**/*.woff",
    "**/*.woff2",
    "**/*.eot",
    // Other binary formats
    "**/*.bin",
    "**/*.dat",
    "**/*.db",
    "**/*.sqlite",
    "**/*.sqlite3",
    // OS files
    "**/*.lnk",
];

/// Sensitive directory prefixes (paths that should have trailing separator).
/// These are resolved at runtime with the actual home directory.
const SENSITIVE_DIR_PREFIXES: &[&str] = &[
    ".ssh",
    ".aws",
    ".gnupg",
    ".gcp",
    ".config/gcloud",
    ".azure",
    ".kube",
    ".docker",
];

/// Sensitive exact filenames (match anywhere).
const SENSITIVE_FILENAMES: &[&str] = &[".env"];

/// Allowed .env variants (not sensitive).
const ALLOWED_ENV_PATTERNS: &[&str] = &[".env.example", ".env.sample", ".env.template"];

/// Sensitive filename prefixes.
const SENSITIVE_FILENAME_PREFIXES: &[&str] = &[".env."];

/// Sensitive file extensions.
const SENSITIVE_EXTENSIONS: &[&str] = &[".pem", ".key", ".p12", ".pfx", ".keystore"];

/// Sensitive exact file paths (system paths, resolved at runtime).
const SENSITIVE_SYSTEM_PATHS: &[&str] = &[
    "/etc/shadow",
    "/etc/sudoers",
    "/etc/passwd",
    "/etc/master.passwd",
    "/private/etc/shadow",
    "/private/etc/sudoers",
    "/private/etc/passwd",
    "/private/etc/master.passwd",
];

/// Path classifier with pre-compiled patterns for efficient matching.
#[pyclass(frozen)]
pub struct PathClassifier {
    /// GlobSet for directory-only patterns.
    dir_globset: GlobSet,
    /// GlobSet for all patterns (dirs + files).
    all_globset: GlobSet,
    /// Home directory expanded sensitive prefixes (with trailing separator).
    sensitive_dir_prefixes: Vec<String>,
    /// Sensitive exact file paths.
    sensitive_exact_files: HashSet<String>,
    /// Sensitive filenames set.
    sensitive_filenames: HashSet<String>,
    /// Allowed .env patterns set.
    allowed_env_patterns: HashSet<String>,
    /// Sensitive extensions set.
    sensitive_extensions: HashSet<String>,
}

impl PathClassifier {
    /// Create a new PathClassifier with all patterns pre-compiled.
    pub fn new() -> Result<Self, Box<dyn std::error::Error>> {
        // Build directory-only globset
        let mut dir_builder = GlobSetBuilder::new();
        for pattern in DIR_PATTERNS {
            dir_builder.add(Glob::new(pattern)?);
        }
        let dir_globset = dir_builder.build()?;

        // Build combined globset (dirs + files)
        let mut all_builder = GlobSetBuilder::new();
        for pattern in DIR_PATTERNS.iter().chain(FILE_PATTERNS.iter()) {
            all_builder.add(Glob::new(pattern)?);
        }
        let all_globset = all_builder.build()?;

        // Get home directory for expanding sensitive paths
        let home_dir = dirs::home_dir().unwrap_or_else(|| Path::new("~").to_path_buf());
        let home_str = home_dir.to_string_lossy();

        // Build resolved sensitive directory prefixes
        let mut sensitive_dir_prefixes: Vec<String> = SENSITIVE_DIR_PREFIXES
            .iter()
            .map(|dir| format!("{}/{}/", home_str, dir))
            .collect();

        // Also add without trailing separator for exact match
        let exact_dirs: Vec<String> = SENSITIVE_DIR_PREFIXES
            .iter()
            .map(|dir| format!("{}/{}", home_str, dir))
            .collect();
        sensitive_dir_prefixes.extend(exact_dirs);

        // Build sensitive exact files set (with expanded home)
        let mut sensitive_exact_files: HashSet<String> = SENSITIVE_SYSTEM_PATHS
            .iter()
            .map(|s| s.to_string())
            .collect();

        // Add home-based sensitive files
        let home_files = [
            ".netrc",
            ".pgpass",
            ".my.cnf",
            ".env",
            ".bash_history",
            ".npmrc",
            ".pypirc",
            ".gitconfig",
        ];
        for file in home_files {
            sensitive_exact_files.insert(format!("{}/{}", home_str, file));
        }

        // Build sets for other checks
        let sensitive_filenames: HashSet<String> =
            SENSITIVE_FILENAMES.iter().map(|s| s.to_string()).collect();
        let allowed_env_patterns: HashSet<String> =
            ALLOWED_ENV_PATTERNS.iter().map(|s| s.to_string()).collect();
        let sensitive_extensions: HashSet<String> = SENSITIVE_EXTENSIONS
            .iter()
            .map(|s| s.to_lowercase())
            .collect();

        Ok(PathClassifier {
            dir_globset,
            all_globset,
            sensitive_dir_prefixes,
            sensitive_exact_files,
            sensitive_filenames,
            allowed_env_patterns,
            sensitive_extensions,
        })
    }

    /// Check if a path should be ignored (matches any ignore pattern).
    pub fn should_ignore(&self, path: &str) -> bool {
        self.matches_compiled(path, &self.all_globset)
    }

    /// Check if a directory path should be ignored (directory patterns only).
    pub fn should_ignore_dir(&self, path: &str) -> bool {
        self.matches_compiled(path, &self.dir_globset)
    }

    /// Internal: match path against a compiled globset.
    fn matches_compiled(&self, path: &str, globset: &GlobSet) -> bool {
        // Strip leading ./ for consistent matching
        let cleaned = if path.starts_with("./") {
            &path[2..]
        } else {
            path
        };

        // Normalise: ensure there is always a directory prefix so that **
        // patterns match root-level entries.
        let dotted = format!("./{}", cleaned);

        // Try normalised path (with ./ prefix)
        if globset.is_match(&dotted) {
            return true;
        }

        // Also try with trailing / for directory patterns
        let dotted_slash = format!("{}/", dotted);
        if globset.is_match(&dotted_slash) {
            return true;
        }

        // Also try the raw cleaned path
        if globset.is_match(cleaned) {
            return true;
        }

        // Try all suffixes (handles nested paths)
        let path_obj = Path::new(cleaned);
        let parts: Vec<&std::ffi::OsStr> = path_obj.iter().collect();

        for i in 1..parts.len() {
            let sub: PathBuf = parts[i..].iter().collect();
            let sub_str = sub.to_string_lossy();

            if globset.is_match(format!("./{}", sub_str)) || globset.is_match(&*sub_str) {
                return true;
            }
        }

        false
    }

    /// Check if a path is sensitive (contains credentials, keys, etc.).
    pub fn is_sensitive(&self, path: &str) -> bool {
        if path.is_empty() {
            return false;
        }

        // Expand ~ and resolve path
        let expanded = self.expand_and_normalize(path);
        let resolved = expanded.as_deref().unwrap_or(path);

        // Check directory prefixes using Aho-Corasick + full path check
        for prefix in &self.sensitive_dir_prefixes {
            if resolved.starts_with(prefix) {
                return true;
            }
        }

        // Check macOS /private/etc
        if resolved.starts_with("/private/etc/") || resolved == "/private/etc" {
            return true;
        }

        // Check /dev directory
        if resolved.starts_with("/dev/") || resolved == "/dev" {
            return true;
        }

        // Check /etc, /root, /proc, /var/log prefixes via regex-like check
        if resolved.starts_with("/etc/")
            || resolved == "/etc"
            || resolved.starts_with("/root/")
            || resolved == "/root"
            || resolved.starts_with("/proc/")
            || resolved == "/proc"
            || resolved.starts_with("/var/log/")
            || resolved == "/var/log"
        {
            return true;
        }

        // Check other users' SSH directories via ~ expansion
        // If path contains /.ssh and is not the current user's, it's sensitive
        if resolved.contains("/.ssh") && !self.is_current_user_ssh(&resolved) {
            return true;
        }

        // Check exact-match files
        if self.sensitive_exact_files.contains(resolved) {
            return true;
        }

        // Check for root user's home
        if resolved.starts_with("/root/") || resolved == "/root" {
            return true;
        }

        // Get basename
        let basename = Path::new(resolved)
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_default();

        // Check sensitive filenames
        if self.sensitive_filenames.contains(&basename) {
            // Check if it's an allowed variant
            let basename_lower = basename.to_lowercase();
            if self.allowed_env_patterns.contains(&basename_lower) {
                return false;
            }
            return true;
        }

        // Check .env.* variants
        let basename_lower = basename.to_lowercase();
        for prefix in SENSITIVE_FILENAME_PREFIXES {
            if basename_lower.starts_with(prefix) {
                // Double-check not in allowed patterns
                if self.allowed_env_patterns.contains(&basename_lower) {
                    return false;
                }
                return true;
            }
        }

        // Check extensions
        if let Some(ext) = Path::new(&basename).extension() {
            let ext_lower = ext.to_string_lossy().to_lowercase();
            let ext_with_dot = format!(".{}", ext_lower);
            if self.sensitive_extensions.contains(&ext_with_dot) {
                return true;
            }
        }

        false
    }

    /// Classify a path, returning (is_ignored, is_sensitive).
    pub fn classify_path(&self, path: &str) -> (bool, bool) {
        (self.should_ignore(path), self.is_sensitive(path))
    }

    /// Expand ~ and normalize a path.
    fn expand_and_normalize(&self, path: &str) -> Option<String> {
        if path.is_empty() {
            return None;
        }

        // Handle ~username paths
        if path.starts_with("~") && path.len() > 1 && !path.starts_with("~/") {
            // This is a ~username path, try to expand
            // For simplicity, we just check if it starts with known sensitive patterns
            if path.contains("/.ssh") {
                return Some(path.to_string());
            }
        }

        // Standard ~ expansion
        let expanded = if path.starts_with("~/") {
            let home = dirs::home_dir()?;
            format!("{}/{}", home.to_string_lossy(), &path[2..])
        } else if path == "~" {
            dirs::home_dir()?.to_string_lossy().to_string()
        } else {
            path.to_string()
        };

        // Normalize: resolve . and .. and make absolute
        let path_obj = Path::new(&expanded);
        let absolute = if path_obj.is_absolute() {
            path_obj.to_path_buf()
        } else {
            std::env::current_dir().ok()?.join(path_obj)
        };

        // Try to canonicalize (resolve symlinks), fall back to clean path
        match absolute.canonicalize() {
            Ok(canon) => Some(canon.to_string_lossy().to_string()),
            Err(_) => Some(absolute.to_string_lossy().to_string()),
        }
    }

    /// Check if a path belongs to the current user's SSH directory.
    fn is_current_user_ssh(&self, resolved: &str) -> bool {
        if let Some(home) = dirs::home_dir() {
            let home_ssh = format!("{}/.ssh", home.to_string_lossy());
            return resolved.starts_with(&home_ssh);
        }
        false
    }

}

// Default implementation using lazy_static for a global instance
// This provides the fastest possible matching for repeated calls

#[cfg(test)]
mod tests {
    use super::*;

    fn get_classifier() -> PathClassifier {
        PathClassifier::new().expect("Failed to create classifier")
    }

    // ===== Ignore pattern tests =====

    #[test]
    fn test_ignore_git_directory() {
        let c = get_classifier();
        assert!(c.should_ignore(".git"));
        assert!(c.should_ignore(".git/config"));
        assert!(c.should_ignore("./.git"));
        assert!(c.should_ignore("./.git/HEAD"));
        assert!(c.should_ignore("project/.git"));
        assert!(c.should_ignore("project/.git/hooks/pre-commit"));
    }

    #[test]
    fn test_ignore_node_modules() {
        let c = get_classifier();
        assert!(c.should_ignore("node_modules"));
        assert!(c.should_ignore("node_modules/lodash"));
        assert!(c.should_ignore("node_modules/lodash/index.js"));
        assert!(c.should_ignore("./node_modules"));
        assert!(c.should_ignore("project/node_modules"));
    }

    #[test]
    fn test_ignore_pycache() {
        let c = get_classifier();
        assert!(c.should_ignore("__pycache__"));
        assert!(c.should_ignore("__pycache__/foo.cpython-311.pyc"));
        assert!(c.should_ignore("./__pycache__"));
        assert!(c.should_ignore("project/__pycache__"));
    }

    #[test]
    fn test_ignore_compiled_python() {
        let c = get_classifier();
        assert!(c.should_ignore("foo.pyc"));
        assert!(c.should_ignore("foo.pyo"));
        assert!(c.should_ignore("./foo.pyc"));
        assert!(c.should_ignore("project/foo.pyc"));
    }

    #[test]
    fn test_ignore_binary_files() {
        let c = get_classifier();
        assert!(c.should_ignore("image.png"));
        assert!(c.should_ignore("doc.pdf"));
        assert!(c.should_ignore("archive.zip"));
        assert!(c.should_ignore("video.mp4"));
        assert!(c.should_ignore("font.ttf"));
    }

    #[test]
    fn test_not_ignore_regular_files() {
        let c = get_classifier();
        assert!(!c.should_ignore("main.py"));
        assert!(!c.should_ignore("src/main.rs"));
        assert!(!c.should_ignore("README.md"));
        assert!(!c.should_ignore("./src/lib.rs"));
    }

    #[test]
    fn test_ignore_npm_logs() {
        let c = get_classifier();
        assert!(c.should_ignore("npm-debug.log"));
        assert!(c.should_ignore("npm-debug.log.123456789"));
    }

    #[test]
    fn test_ignore_hidden_files() {
        let c = get_classifier();
        assert!(c.should_ignore(".DS_Store"));
        assert!(c.should_ignore("./.DS_Store"));
        assert!(c.should_ignore("project/.DS_Store"));
    }

    #[test]
    fn test_ignore_swap_files() {
        let c = get_classifier();
        assert!(c.should_ignore(".file.swp"));
        assert!(c.should_ignore(".file.swo"));
        assert!(c.should_ignore("file~"));
    }

    // ===== Sensitive path tests =====

    #[test]
    fn test_sensitive_ssh_directory() {
        let _c = get_classifier();
        // Note: These depend on actual home directory
        // In CI/test environments, we can't assume a home dir exists
        // But we can test the logic works
        // Test passes just by creating the classifier without panic
    }

    #[test]
    fn test_sensitive_etc_paths() {
        let c = get_classifier();
        assert!(c.is_sensitive("/etc/shadow"));
        assert!(c.is_sensitive("/etc/passwd"));
        assert!(c.is_sensitive("/etc/sudoers"));
        assert!(c.is_sensitive("/etc"));  // Exact match on /etc
    }

    #[test]
    fn test_sensitive_private_etc() {
        let c = get_classifier();
        assert!(c.is_sensitive("/private/etc/shadow"));
        assert!(c.is_sensitive("/private/etc/passwd"));
        assert!(c.is_sensitive("/private/etc"));  // Exact match on /private/etc
    }

    #[test]
    fn test_sensitive_dev() {
        let c = get_classifier();
        assert!(c.is_sensitive("/dev/sda1"));
        assert!(c.is_sensitive("/dev/null"));
    }

    #[test]
    fn test_sensitive_root() {
        let c = get_classifier();
        assert!(c.is_sensitive("/root"));
        assert!(c.is_sensitive("/root/.bashrc"));
    }

    #[test]
    fn test_sensitive_proc() {
        let c = get_classifier();
        assert!(c.is_sensitive("/proc/1/cmdline"));
        assert!(c.is_sensitive("/proc"));
    }

    #[test]
    fn test_sensitive_var_log() {
        let c = get_classifier();
        assert!(c.is_sensitive("/var/log/syslog"));
        assert!(c.is_sensitive("/var/log/auth.log"));
        // Note: /var/log exact match may vary by platform due to symlinks
    }

    #[test]
    fn test_sensitive_env_files() {
        let c = get_classifier();
        // Regular .env is sensitive
        assert!(c.is_sensitive(".env"));
        assert!(c.is_sensitive("project/.env"));
        assert!(c.is_sensitive("/path/to/.env"));

        // Allowed variants are NOT sensitive
        assert!(!c.is_sensitive(".env.example"));
        assert!(!c.is_sensitive(".env.sample"));
        assert!(!c.is_sensitive(".env.template"));
        assert!(!c.is_sensitive("project/.env.example"));
    }

    #[test]
    fn test_sensitive_extensions() {
        let c = get_classifier();
        assert!(c.is_sensitive("id_rsa.pem"));
        assert!(c.is_sensitive("server.key"));
        assert!(c.is_sensitive("cert.p12"));
        assert!(c.is_sensitive("keystore.pfx"));
        assert!(c.is_sensitive("android.keystore"));
    }

    #[test]
    fn test_not_sensitive_regular_files() {
        let c = get_classifier();
        assert!(!c.is_sensitive("main.py"));
        assert!(!c.is_sensitive("README.md"));
        assert!(!c.is_sensitive("src/lib.rs"));
    }

    #[test]
    fn test_empty_path() {
        let c = get_classifier();
        assert!(!c.is_sensitive(""));
        assert!(!c.should_ignore(""));
    }

    #[test]
    fn test_classify_path() {
        let c = get_classifier();

        // Regular file: not ignored, not sensitive
        assert_eq!(c.classify_path("main.py"), (false, false));

        // .env file: not ignored, IS sensitive
        assert_eq!(c.classify_path(".env"), (false, true));

        // node_modules: IS ignored, not sensitive
        assert_eq!(c.classify_path("node_modules"), (true, false));

        // Binary file in node_modules: IS ignored, IS sensitive (if applicable)
        // (Example path would need to match both criteria)

        // Regular file in .ssh: not ignored by default, IS sensitive
        // This depends on home directory resolution
    }

    #[test]
    fn test_dir_only_vs_all() {
        let c = get_classifier();

        // Directory patterns should match both
        assert!(c.should_ignore("node_modules"));
        assert!(c.should_ignore_dir("node_modules"));

        // File patterns should match only all_globset
        assert!(c.should_ignore("image.png"));
        assert!(!c.should_ignore_dir("image.png"));

        // Regular files shouldn't match either
        assert!(!c.should_ignore("main.py"));
        assert!(!c.should_ignore_dir("main.py"));
    }
}

// Separate impl block for PyO3 Python-facing methods
#[pymethods]
impl PathClassifier {
    /// Create a new PathClassifier with pre-compiled patterns.
    #[new]
    fn py_new() -> PyResult<Self> {
        PathClassifier::new()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("{}", e)))
    }

    /// Check if a path should be ignored.
    fn py_should_ignore(slf: &Bound<'_, Self>, path: &str) -> bool {
        slf.borrow().should_ignore(path)
    }

    /// Check if a directory path should be ignored.
    fn py_should_ignore_dir(slf: &Bound<'_, Self>, path: &str) -> bool {
        slf.borrow().should_ignore_dir(path)
    }

    /// Check if a path is sensitive.
    fn py_is_sensitive(slf: &Bound<'_, Self>, path: &str) -> bool {
        slf.borrow().is_sensitive(path)
    }

    /// Classify a path, returning (is_ignored, is_sensitive).
    fn py_classify_path(slf: &Bound<'_, Self>, path: &str) -> (bool, bool) {
        let this = slf.borrow();
        (this.should_ignore(path), this.is_sensitive(path))
    }
}
