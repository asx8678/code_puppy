//! Path classification for ignore and sensitive path detection.
//!
//! This module provides fast path classification using pre-compiled patterns:
//! - `globset` for gitignore-style glob matching
//!
//! Ported from Python: `should_ignore_path()` and `is_sensitive_path()`
//! from `code_puppy/tools/common.py` and `code_puppy/sensitive_paths.py`

use globset::{Glob, GlobSet, GlobSetBuilder};
use pyo3::prelude::*;
use std::path::{Path, PathBuf};

mod patterns;
mod sensitive;

// Public exports available through crate::path_classify
pub use sensitive::SensitivePathData;

use patterns::{DIR_PATTERNS as DIR_PATTERNS_CONST, FILE_PATTERNS as FILE_PATTERNS_CONST};

/// Path classifier with pre-compiled patterns for efficient matching.
#[pyclass(frozen)]
pub struct PathClassifier {
    /// GlobSet for directory-only patterns.
    dir_globset: GlobSet,
    /// GlobSet for all patterns (dirs + files).
    all_globset: GlobSet,
    /// Sensitive path data for is_sensitive checks.
    sensitive_data: SensitivePathData,
}

impl PathClassifier {
    /// Create a new PathClassifier with all patterns pre-compiled.
    pub fn new() -> Result<Self, Box<dyn std::error::Error>> {
        // Build directory-only globset
        let mut dir_builder = GlobSetBuilder::new();
        for pattern in DIR_PATTERNS_CONST {
            dir_builder.add(Glob::new(pattern)?);
        }
        let dir_globset = dir_builder.build()?;

        // Build combined globset (dirs + files)
        let mut all_builder = GlobSetBuilder::new();
        for pattern in DIR_PATTERNS_CONST.iter().chain(FILE_PATTERNS_CONST.iter()) {
            all_builder.add(Glob::new(pattern)?);
        }
        let all_globset = all_builder.build()?;

        // Create sensitive path data
        let sensitive_data = SensitivePathData::new()?;

        Ok(PathClassifier {
            dir_globset,
            all_globset,
            sensitive_data,
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
        let cleaned = if let Some(stripped) = path.strip_prefix("./") {
            stripped
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

        // bd-28: Check for hidden files/directories (dotfiles/dotdirs)
        // This implements the "**/.*" pattern requested for Python parity.
        // We do this check in code rather than via glob patterns because globset
        // incorrectly interprets ".*" as "match everything" (regex semantics)
        // instead of "literal dot followed by anything" (glob semantics).
        // Note: The bare "." (current dir) is treated as hidden here too,
        // which matches Python's **/.* behavior.
        for part in &parts {
            if let Some(s) = part.to_str() {
                // Only exclude the literal ".." (parent dir navigation).
                // Names like "..hidden" or "...hidden" ARE hidden (start with dot).
                if s.starts_with('.') && s != ".." {
                    return true;
                }
            }
        }

        false
    }

    /// Check if a path is sensitive (contains credentials, keys, etc.).
    pub fn is_sensitive(&self, path: &str) -> bool {
        self.sensitive_data.is_sensitive(path)
    }

    /// Classify a path, returning (is_ignored, is_sensitive).
    pub fn classify_path(&self, path: &str) -> (bool, bool) {
        (self.should_ignore(path), self.is_sensitive(path))
    }
}

#[cfg(test)]
mod tests;

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
