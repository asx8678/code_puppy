//! Sensitive path detection logic.
//!
//! This module provides detection of sensitive paths (credentials, keys, etc.)
//! Ported from Python: `code_puppy/sensitive_paths.py` `is_sensitive_path()`

use std::collections::HashSet;
use std::path::Path;

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

/// Pre-computed sensitive path data resolved at classifier creation time.
pub struct SensitivePathData {
    /// Home directory expanded sensitive prefixes (with trailing separator).
    pub sensitive_dir_prefixes: Vec<String>,
    /// Sensitive exact file paths.
    pub sensitive_exact_files: HashSet<String>,
    /// Sensitive filenames set.
    pub sensitive_filenames: HashSet<String>,
    /// Allowed .env patterns set.
    pub allowed_env_patterns: HashSet<String>,
    /// Sensitive extensions set.
    pub sensitive_extensions: HashSet<String>,
}

impl SensitivePathData {
    /// Create new sensitive path data with resolved home directory paths.
    pub fn new() -> Result<Self, Box<dyn std::error::Error>> {
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

        Ok(SensitivePathData {
            sensitive_dir_prefixes,
            sensitive_exact_files,
            sensitive_filenames,
            allowed_env_patterns,
            sensitive_extensions,
        })
    }

    /// Check if a path is sensitive (contains credentials, keys, etc.).
    /// NOTE: This must match Python `is_sensitive_path()` behavior exactly.
    pub fn is_sensitive(&self, path: &str) -> bool {
        if path.is_empty() {
            return false;
        }

        // Check for ~username paths (e.g., ~root, ~other)
        // These need special handling before path normalization
        if let Some(sensitive_tilde) = self.check_tilde_username_paths(path) {
            return sensitive_tilde;
        }

        // Expand ~ and resolve path
        let expanded = self.expand_and_normalize(path);
        let resolved = expanded.as_deref().unwrap_or(path);

        // Check directory prefixes
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

        // Check exact-match files
        if self.sensitive_exact_files.contains(resolved) {
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

    /// Check ~username paths for sensitive directories.
    /// Returns Some(true) if sensitive, Some(false) if safe, None if not a ~username path.
    fn check_tilde_username_paths(&self, path: &str) -> Option<bool> {
        // Check if path starts with ~ followed by a username (not ~/)
        if !path.starts_with("~") || path.len() <= 1 || path.starts_with("~/") {
            return None;
        }

        // This is a ~username path - check for sensitive patterns
        // ~username/.ssh should always be sensitive (other user's SSH keys)
        if path.contains("/.ssh") {
            return Some(true);
        }

        // Check for ~root (root user's home directory)
        if path.starts_with("~root") {
            return Some(true);
        }

        // Other ~username paths that don't match specific sensitive patterns
        // are considered safe for this check
        Some(false)
    }

    /// Expand ~ and normalize a path.
    fn expand_and_normalize(&self, path: &str) -> Option<String> {
        if path.is_empty() {
            return None;
        }

        // Handle ~username paths
        if path.starts_with("~") && path.len() > 1 && !path.starts_with("~/") {
            // This is a ~username path, check if it contains /.ssh
            if path.contains("/.ssh") {
                return Some(path.to_string());
            }
        }

        // Standard ~ expansion
        let expanded = if let Some(stripped) = path.strip_prefix("~/") {
            let home = dirs::home_dir()?;
            format!("{}/{}", home.to_string_lossy(), stripped)
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
}
