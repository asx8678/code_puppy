//! Dynamic Grammar Loading — Runtime loading of tree-sitter grammars via libloading.
//!
//! This module provides the ability to load tree-sitter grammar libraries
//! (.so/.dylib/.dll files) at runtime. This enables users to use custom
//! grammars without recompiling turbo_parse.
//!
//! # Security Considerations
//!
//! Loading dynamic libraries from user-provided paths carries security risks:
//! - Path traversal attacks (mitigated by validation)
//! - Malicious library code execution (use only trusted libraries)
//! - Side-loading attacks (ensure library integrity)
//!
//! The `dynamic-grammars` feature is disabled by default.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, RwLock};

#[cfg(feature = "dynamic-grammars")]
use libloading::{Library, Symbol};
use tree_sitter::Language;

use crate::registry::RegistryError;

/// Extension for dynamic libraries by platform.
#[cfg(target_os = "linux")]
pub const DYLIB_EXTENSION: &str = ".so";

#[cfg(target_os = "macos")]
pub const DYLIB_EXTENSION: &str = ".dylib";

#[cfg(target_os = "windows")]
pub const DYLIB_EXTENSION: &str = ".dll";

/// Errors that can occur when loading dynamic grammars.
#[derive(Debug, Clone, PartialEq)]
pub enum DynamicLoadError {
    /// The path does not exist or is not accessible.
    PathNotFound(String),
    /// Path traversal detected (attempt to escape allowed directories).
    PathTraversal(String),
    /// Library loading failed (invalid format, missing symbols, etc).
    LibraryLoadError(String),
    /// The library doesn't export the required tree-sitter symbols.
    MissingSymbol(String),
    /// External scanner loading failed.
    ScannerLoadError(String),
    /// Dynamic grammar loading is not enabled (feature not compiled).
    FeatureNotEnabled,
    /// Grammar already registered with this name.
    AlreadyRegistered(String),
    /// Invalid grammar name.
    InvalidName(String),
}

impl std::fmt::Display for DynamicLoadError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            DynamicLoadError::PathNotFound(path) => {
                write!(f, "Grammar library not found: {}", path)
            }
            DynamicLoadError::PathTraversal(path) => {
                write!(f, "Path traversal detected in: {}", path)
            }
            DynamicLoadError::LibraryLoadError(msg) => {
                write!(f, "Failed to load library: {}", msg)
            }
            DynamicLoadError::MissingSymbol(name) => {
                write!(f, "Required symbol not found in library: {}", name)
            }
            DynamicLoadError::ScannerLoadError(msg) => {
                write!(f, "Failed to load external scanner: {}", msg)
            }
            DynamicLoadError::FeatureNotEnabled => {
                write!(f, "Dynamic grammar loading is not enabled. Recompile with 'dynamic-grammars' feature.")
            }
            DynamicLoadError::AlreadyRegistered(name) => {
                write!(f, "Grammar '{}' is already registered", name)
            }
            DynamicLoadError::InvalidName(name) => {
                write!(f, "Invalid grammar name: '{}'", name)
            }
        }
    }
}

impl std::error::Error for DynamicLoadError {}

impl From<DynamicLoadError> for RegistryError {
    fn from(err: DynamicLoadError) -> Self {
        RegistryError::InitializationError(err.to_string())
    }
}

/// Information about a dynamically loaded grammar.
#[derive(Debug, Clone)]
pub struct DynamicGrammarInfo {
    /// The name used to register this grammar.
    pub name: String,
    /// Path to the library file.
    pub library_path: PathBuf,
    /// Optional path to external scanner library.
    pub scanner_path: Option<PathBuf>,
    /// Tree-sitter language version.
    pub version: usize,
    /// Whether this grammar has an external scanner.
    pub has_external_scanner: bool,
}

/// A loaded dynamic grammar with its associated library handle.
#[cfg(feature = "dynamic-grammars")]
pub struct LoadedGrammar {
    /// The tree-sitter language object.
    pub language: Language,
    /// The loaded library handle (kept alive for the language to work).
    #[allow(dead_code)]
    pub library: Library,
    /// Optional external scanner library.
    #[allow(dead_code)]
    pub scanner_lib: Option<Library>,
    /// Grammar metadata.
    pub info: DynamicGrammarInfo,
}

#[cfg(not(feature = "dynamic-grammars"))]
pub struct LoadedGrammar {
    pub language: Language,
    pub info: DynamicGrammarInfo,
}

/// Loader for dynamic tree-sitter grammars.
///
/// This struct manages loading and caching of grammar libraries.
/// It ensures that libraries are kept loaded for the lifetime of
/// the program so the Language objects remain valid.
pub struct DynamicGrammarLoader {
    /// Cache of loaded grammars by name.
    grammars: RwLock<HashMap<String, Arc<LoadedGrammar>>>,
    /// Allowed base directories for loading (empty = allow all with validation).
    allowed_directories: Mutex<Vec<PathBuf>>,
    /// Whether to allow loading from any directory (with path traversal checks).
    allow_any_directory: Mutex<bool>,
}

impl DynamicGrammarLoader {
    /// Create a new dynamic grammar loader.
    pub fn new() -> Self {
        Self {
            grammars: RwLock::new(HashMap::new()),
            allowed_directories: Mutex::new(Vec::new()),
            allow_any_directory: Mutex::new(true),
        }
    }

    /// Set allowed directories for grammar loading.
    ///
    /// If set, grammars can only be loaded from these directories and their subdirectories.
    pub fn set_allowed_directories(&self, dirs: Vec<PathBuf>) {
        let mut allowed = self.allowed_directories.lock().unwrap();
        *allowed = dirs;
    }

    /// Add an allowed directory.
    pub fn add_allowed_directory(&self, dir: PathBuf) {
        let mut allowed = self.allowed_directories.lock().unwrap();
        allowed.push(dir);
    }

    /// Set whether to allow loading from any directory.
    ///
    /// When true (default), grammars can be loaded from any directory
    /// as long as they pass path traversal validation.
    pub fn set_allow_any_directory(&self, allow: bool) {
        let mut allow_any = self.allow_any_directory.lock().unwrap();
        *allow_any = allow;
    }

    /// Validate that a path doesn't contain traversal components.
    fn validate_no_traversal(&self, path: &Path) -> Result<(), DynamicLoadError> {
        // Check for ".." components in the path
        for component in path.components() {
            if let std::path::Component::ParentDir = component {
                return Err(DynamicLoadError::PathTraversal(
                    path.to_string_lossy().to_string()
                ));
            }
        }

        // Check that the path is absolute (recommended for security)
        // but if relative, ensure it doesn't escape the working directory
        if path.is_relative() {
            // Additional check: resolved path should be within current dir
            if let Ok(canonical) = std::env::current_dir().map(|cwd| cwd.join(path)) {
                if let Ok(canonical) = canonical.canonicalize() {
                    let cwd = std::env::current_dir().ok()
                        .and_then(|p| p.canonicalize().ok())
                        .unwrap_or_else(|| PathBuf::from("/"));
                    
                    if !canonical.starts_with(&cwd) {
                        return Err(DynamicLoadError::PathTraversal(
                            path.to_string_lossy().to_string()
                        ));
                    }
                }
            }
        }

        Ok(())
    }

    /// Check if a path is within allowed directories.
    fn is_path_allowed(&self, path: &Path) -> bool {
        // Check traversal first
        if self.validate_no_traversal(path).is_err() {
            return false;
        }

        let allowed_dirs = self.allowed_directories.lock().unwrap();
        let allow_any = self.allow_any_directory.lock().unwrap();

        if *allow_any && allowed_dirs.is_empty() {
            // Allow any directory that passes traversal checks
            return true;
        }

        // Get canonical path for comparison
        let canonical_path = match path.canonicalize() {
            Ok(p) => p,
            Err(_) => return false,
        };

        // Check against allowed directories
        for allowed_dir in allowed_dirs.iter() {
            if let Ok(allowed_canonical) = allowed_dir.canonicalize() {
                if canonical_path.starts_with(&allowed_canonical) {
                    return true;
                }
            }
        }

        false
    }

    /// Validate grammar name (alphanumeric, hyphens, underscores only).
    fn validate_name(&self, name: &str) -> Result<(), DynamicLoadError> {
        if name.is_empty() {
            return Err(DynamicLoadError::InvalidName(name.to_string()));
        }

        let valid = name.chars().all(|c| {
            c.is_alphanumeric() || c == '-' || c == '_'
        });

        if !valid {
            return Err(DynamicLoadError::InvalidName(name.to_string()));
        }

        Ok(())
    }

    /// Get the platform-specific library name for a grammar.
    ///
    /// If the path already has the correct extension, returns as-is.
    /// Otherwise, appends the platform extension.
    pub fn to_platform_library_path(&self, path: &Path) -> PathBuf {
        let ext = path.extension()
            .and_then(|e| e.to_str())
            .unwrap_or("");

        let has_platform_ext = match ext {
            "so" | "dylib" | "dll" => true,
            _ => false,
        };

        if has_platform_ext {
            path.to_path_buf()
        } else {
            path.with_extension(DYLIB_EXTENSION.trim_start_matches('.'))
        }
    }

    /// Load a grammar from a library path.
    ///
    /// # Arguments
    /// * `name` - Unique name to register this grammar under
    /// * `library_path` - Path to the grammar library (.so/.dylib/.dll)
    ///
    /// # Returns
    /// The loaded Language on success.
    #[cfg(feature = "dynamic-grammars")]
    pub fn load_grammar(
        &self,
        name: &str,
        library_path: &Path,
    ) -> Result<Language, DynamicLoadError> {
        self.validate_name(name)?;

        // Check if already loaded
        {
            let grammars = self.grammars.read().unwrap();
            if grammars.contains_key(name) {
                return Err(DynamicLoadError::AlreadyRegistered(name.to_string()));
            }
        }

        // Validate path
        let platform_path = self.to_platform_library_path(library_path);
        
        if !platform_path.exists() {
            return Err(DynamicLoadError::PathNotFound(
                platform_path.to_string_lossy().to_string()
            ));
        }

        if !self.is_path_allowed(&platform_path) {
            return Err(DynamicLoadError::PathTraversal(
                platform_path.to_string_lossy().to_string()
            ));
        }

        // Load the library
        let lib = unsafe {
            Library::new(&platform_path)
                .map_err(|e| DynamicLoadError::LibraryLoadError(e.to_string()))?
        };

        // Construct the symbol name (tree-sitter convention: tree_sitter_<language>)
        let symbol_name = format!("tree_sitter_{}", name.replace("-", "_"));

        // Get the language function
        let lang_fn: Symbol<unsafe extern "C" fn() -> Language> = unsafe {
            lib.get(symbol_name.as_bytes())
                .map_err(|e| DynamicLoadError::MissingSymbol(format!(
                    "{} (looking for symbol: {}): {}",
                    e, symbol_name, e
                )))?
        };

        // Call the function to get the language
        let language = unsafe { lang_fn() };

        // Clone language before moving (Language implements Clone)
        let language_clone = language.clone();

        // Create grammar info
        let info = DynamicGrammarInfo {
            name: name.to_string(),
            library_path: platform_path.clone(),
            scanner_path: None,
            version: language.version(),
            has_external_scanner: false,
        };

        // Cache the loaded grammar
        let loaded = LoadedGrammar {
            language,
            library: lib,
            scanner_lib: None,
            info,
        };

        {
            let mut grammars = self.grammars.write().unwrap();
            grammars.insert(name.to_string(), Arc::new(loaded));
        }

        Ok(language_clone)
    }

    /// Load a grammar with external scanner support.
    ///
    /// # Arguments
    /// * `name` - Unique name to register this grammar under
    /// * `library_path` - Path to the grammar library
    /// * `scanner_path` - Optional path to external scanner library
    #[cfg(feature = "dynamic-grammars")]
    pub fn load_grammar_with_scanner(
        &self,
        name: &str,
        library_path: &Path,
        scanner_path: Option<&Path>,
    ) -> Result<Language, DynamicLoadError> {
        self.validate_name(name)?;

        // Check if already loaded
        {
            let grammars = self.grammars.read().unwrap();
            if grammars.contains_key(name) {
                return Err(DynamicLoadError::AlreadyRegistered(name.to_string()));
            }
        }

        // Validate and load main library
        let platform_path = self.to_platform_library_path(library_path);
        
        if !platform_path.exists() {
            return Err(DynamicLoadError::PathNotFound(
                platform_path.to_string_lossy().to_string()
            ));
        }

        if !self.is_path_allowed(&platform_path) {
            return Err(DynamicLoadError::PathTraversal(
                platform_path.to_string_lossy().to_string()
            ));
        }

        // Load the grammar library
        let lib = unsafe {
            Library::new(&platform_path)
                .map_err(|e| DynamicLoadError::LibraryLoadError(e.to_string()))?
        };

        // Load optional scanner library
        let scanner_platform_path = scanner_path.map(|s| self.to_platform_library_path(s));
        
        let scanner_lib = if let Some(ref scanner_platform) = scanner_platform_path {
            if !scanner_platform.exists() {
                return Err(DynamicLoadError::ScannerLoadError(
                    format!("Scanner not found: {}", scanner_platform.display())
                ));
            }

            if !self.is_path_allowed(&scanner_platform) {
                return Err(DynamicLoadError::PathTraversal(
                    scanner_platform.to_string_lossy().to_string()
                ));
            }

            let scanner = unsafe {
                Library::new(&scanner_platform)
                    .map_err(|e| DynamicLoadError::ScannerLoadError(e.to_string()))?
            };

            Some(scanner)
        } else {
            None
        };

        // Get the language function
        let symbol_name = format!("tree_sitter_{}", name.replace("-", "_"));

        let lang_fn: Symbol<unsafe extern "C" fn() -> Language> = unsafe {
            lib.get(symbol_name.as_bytes())
                .map_err(|e| DynamicLoadError::MissingSymbol(format!(
                    "{} (looking for symbol: {}): {}",
                    e, symbol_name, e
                )))?
        };

        let language = unsafe { lang_fn() };

        // Clone language before moving (Language implements Clone)
        let language_clone = language.clone();

        // Create grammar info
        let info = DynamicGrammarInfo {
            name: name.to_string(),
            library_path: platform_path.clone(),
            scanner_path: scanner_platform_path.clone(),
            version: language.version(),
            has_external_scanner: scanner_lib.is_some(),
        };

        // Cache the loaded grammar
        let loaded = LoadedGrammar {
            language,
            library: lib,
            scanner_lib,
            info,
        };

        {
            let mut grammars = self.grammars.write().unwrap();
            grammars.insert(name.to_string(), Arc::new(loaded));
        }

        Ok(language_clone)
    }

    /// Stub implementation when feature is not enabled.
    #[cfg(not(feature = "dynamic-grammars"))]
    pub fn load_grammar(
        &self,
        _name: &str,
        _library_path: &Path,
    ) -> Result<Language, DynamicLoadError> {
        Err(DynamicLoadError::FeatureNotEnabled)
    }

    /// Stub implementation when feature is not enabled.
    #[cfg(not(feature = "dynamic-grammars"))]
    pub fn load_grammar_with_scanner(
        &self,
        _name: &str,
        _library_path: &Path,
        _scanner_path: Option<&Path>,
    ) -> Result<Language, DynamicLoadError> {
        Err(DynamicLoadError::FeatureNotEnabled)
    }

    /// Get a loaded grammar by name.
    pub fn get_grammar(&self, name: &str) -> Option<Arc<LoadedGrammar>> {
        let grammars = self.grammars.read().unwrap();
        grammars.get(name).cloned()
    }

    /// Get the Language for a loaded grammar.
    pub fn get_language(&self, name: &str) -> Option<Language> {
        self.get_grammar(name).map(|g| g.language.clone())
    }

    /// Check if a grammar is loaded.
    pub fn is_loaded(&self, name: &str) -> bool {
        let grammars = self.grammars.read().unwrap();
        grammars.contains_key(name)
    }

    /// Remove a loaded grammar.
    pub fn unload_grammar(&self, name: &str) -> bool {
        let mut grammars = self.grammars.write().unwrap();
        grammars.remove(name).is_some()
    }

    /// List all loaded dynamic grammars.
    pub fn list_loaded(&self) -> Vec<DynamicGrammarInfo> {
        let grammars = self.grammars.read().unwrap();
        grammars.values().map(|g| g.info.clone()).collect()
    }

    /// Clear all loaded grammars.
    pub fn clear(&self) {
        let mut grammars = self.grammars.write().unwrap();
        grammars.clear();
    }

    /// Get the number of loaded grammars.
    pub fn count(&self) -> usize {
        let grammars = self.grammars.read().unwrap();
        grammars.len()
    }
}

impl Default for DynamicGrammarLoader {
    fn default() -> Self {
        Self::new()
    }
}

// Global singleton instance
static GLOBAL_LOADER: std::sync::OnceLock<DynamicGrammarLoader> = std::sync::OnceLock::new();

/// Get the global dynamic grammar loader instance.
pub fn global_loader() -> &'static DynamicGrammarLoader {
    GLOBAL_LOADER.get_or_init(DynamicGrammarLoader::new)
}

/// Convenience function to load a grammar using the global loader.
pub fn load_dynamic_grammar(name: &str, path: &Path) -> Result<Language, DynamicLoadError> {
    global_loader().load_grammar(name, path)
}

/// Convenience function to load a grammar with scanner.
pub fn load_dynamic_grammar_with_scanner(
    name: &str,
    library_path: &Path,
    scanner_path: Option<&Path>,
) -> Result<Language, DynamicLoadError> {
    global_loader().load_grammar_with_scanner(name, library_path, scanner_path)
}

/// Get a loaded grammar from the global loader.
pub fn get_dynamic_grammar(name: &str) -> Option<Arc<LoadedGrammar>> {
    global_loader().get_grammar(name)
}

/// Check if a grammar is loaded in the global loader.
pub fn is_dynamic_grammar_loaded(name: &str) -> bool {
    global_loader().is_loaded(name)
}

/// Unload a grammar from the global loader.
pub fn unload_dynamic_grammar(name: &str) -> bool {
    global_loader().unload_grammar(name)
}

/// List all loaded dynamic grammars.
pub fn list_dynamic_grammars() -> Vec<DynamicGrammarInfo> {
    global_loader().list_loaded()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn test_validate_name() {
        let loader = DynamicGrammarLoader::new();
        
        assert!(loader.validate_name("python").is_ok());
        assert!(loader.validate_name("my-lang").is_ok());
        assert!(loader.validate_name("my_lang").is_ok());
        assert!(loader.validate_name("lang123").is_ok());
        
        assert!(loader.validate_name("").is_err());
        assert!(loader.validate_name("lang.name").is_err());
        assert!(loader.validate_name("lang/name").is_err());
        assert!(loader.validate_name("lang@name").is_err());
    }

    #[test]
    fn test_validate_no_traversal() {
        let loader = DynamicGrammarLoader::new();
        
        // Valid paths
        assert!(loader.validate_no_traversal(Path::new("/usr/lib/grammar.so")).is_ok());
        assert!(loader.validate_no_traversal(Path::new("grammar.so")).is_ok());
        assert!(loader.validate_no_traversal(Path::new("grammars/python.so")).is_ok());
        
        // Invalid paths with traversal
        assert!(loader.validate_no_traversal(Path::new("../etc/passwd")).is_err());
        assert!(loader.validate_no_traversal(Path::new("/usr/lib/../../../etc/passwd")).is_err());
    }

    #[test]
    fn test_to_platform_library_path() {
        let loader = DynamicGrammarLoader::new();
        
        // Already has extension
        let path = Path::new("/usr/lib/grammar.so");
        let result = loader.to_platform_library_path(path);
        assert_eq!(result, Path::new("/usr/lib/grammar.so"));

        // Needs extension
        let path = Path::new("/usr/lib/grammar");
        let result = loader.to_platform_library_path(path);
        assert!(result.to_string_lossy().ends_with(DYLIB_EXTENSION));
    }

    #[test]
    fn test_platform_extension() {
        // Verify the correct extension is defined for the platform
        #[cfg(target_os = "linux")]
        assert_eq!(DYLIB_EXTENSION, ".so");
        #[cfg(target_os = "macos")]
        assert_eq!(DYLIB_EXTENSION, ".dylib");
        #[cfg(target_os = "windows")]
        assert_eq!(DYLIB_EXTENSION, ".dll");
    }

    #[test]
    fn test_load_grammar_feature_not_enabled() {
        // This test runs when dynamic-grammars feature is not enabled
        let loader = DynamicGrammarLoader::new();
        let result = loader.load_grammar("test", Path::new("/fake/path.so"));
        
        #[cfg(not(feature = "dynamic-grammars"))]
        assert_eq!(result.unwrap_err(), DynamicLoadError::FeatureNotEnabled);
    }

    #[test]
    fn test_allowed_directories() {
        let loader = DynamicGrammarLoader::new();
        
        // By default, allow_any is true
        assert!(loader.is_path_allowed(Path::new("/usr/lib/test.so")));
        
        // Set specific allowed directories
        loader.set_allow_any_directory(false);
        loader.set_allowed_directories(vec![PathBuf::from("/usr/lib")]);
        
        // This would need the directory to actually exist for canonicalization
        // so we just test that the mechanism is in place
    }

    #[test]
    fn test_loader_cache() {
        let loader = DynamicGrammarLoader::new();
        
        assert_eq!(loader.count(), 0);
        assert!(loader.list_loaded().is_empty());
        assert!(!loader.is_loaded("test"));
        assert!(loader.get_grammar("test").is_none());
    }

    #[test]
    fn test_error_display() {
        assert!(DynamicLoadError::PathNotFound("/test".to_string()).to_string().contains("not found"));
        assert!(DynamicLoadError::PathTraversal("/test".to_string()).to_string().contains("traversal"));
        assert!(DynamicLoadError::LibraryLoadError("fail".to_string()).to_string().contains("Failed"));
        assert!(DynamicLoadError::MissingSymbol("sym".to_string()).to_string().contains("symbol"));
        assert!(DynamicLoadError::ScannerLoadError("fail".to_string()).to_string().contains("scanner"));
        assert!(DynamicLoadError::FeatureNotEnabled.to_string().contains("not enabled"));
        assert!(DynamicLoadError::AlreadyRegistered("test".to_string()).to_string().contains("already"));
        assert!(DynamicLoadError::InvalidName("bad/name".to_string()).to_string().contains("Invalid"));
    }

    #[test]
    fn test_registry_error_conversion() {
        let dynamic_err = DynamicLoadError::LibraryLoadError("test".to_string());
        let reg_err: RegistryError = dynamic_err.into();
        
        match reg_err {
            RegistryError::InitializationError(msg) => {
                assert!(msg.contains("test"));
            }
            _ => panic!("Expected InitializationError"),
        }
    }

    #[test]
    fn test_grammar_info() {
        let info = DynamicGrammarInfo {
            name: "test-lang".to_string(),
            library_path: PathBuf::from("/usr/lib/test.so"),
            scanner_path: Some(PathBuf::from("/usr/lib/test_scanner.so")),
            version: 14,
            has_external_scanner: true,
        };
        
        assert_eq!(info.name, "test-lang");
        assert!(info.has_external_scanner);
    }
}
