//! Dynamic grammar loading module.
//!
//! This module provides runtime loading of tree-sitter grammars from shared libraries.
//! It is only available when the `dynamic-grammars` feature is enabled.

use crate::types::RegistryError;
use std::collections::HashMap;
use std::path::Path;
use std::sync::OnceLock;
use parking_lot::Mutex;
use tree_sitter::Language;

/// Information about a loaded dynamic grammar.
#[derive(Debug, Clone)]
pub struct LoadedGrammar {
    /// The language name.
    pub name: String,
    /// The tree-sitter language.
    pub language: Language,
    /// The library path (if known).
    pub library_path: Option<String>,
}

/// Global loader for dynamic grammars.
pub struct DynamicLoader {
    grammars: Mutex<HashMap<String, LoadedGrammar>>,
}

impl DynamicLoader {
    /// Create a new dynamic loader.
    fn new() -> Self {
        Self {
            grammars: Mutex::new(HashMap::new()),
        }
    }

    /// Get a loaded grammar by name.
    pub fn get_grammar(&self, name: &str) -> Option<LoadedGrammar> {
        let grammars = self.grammars.lock();
        grammars.get(name).cloned()
    }

    /// Check if a grammar is loaded.
    pub fn is_loaded(&self, name: &str) -> bool {
        let grammars = self.grammars.lock();
        grammars.contains_key(name)
    }

    /// List all loaded grammars.
    pub fn list_loaded(&self) -> Vec<LoadedGrammar> {
        let grammars = self.grammars.lock();
        grammars.values().cloned().collect()
    }

    /// Unload a grammar by name.
    pub fn unload_grammar(&self, name: &str) {
        let mut grammars = self.grammars.lock();
        grammars.remove(name);
    }

    /// Store a loaded grammar.
    fn store_grammar(&self, name: String, language: Language, path: Option<String>) {
        let mut grammars = self.grammars.lock();
        grammars.insert(
            name.clone(),
            LoadedGrammar {
                name,
                language,
                library_path: path,
            },
        );
    }
}

// Global static instance for the dynamic loader
static GLOBAL_LOADER: OnceLock<DynamicLoader> = OnceLock::new();

/// Get the global dynamic loader instance.
pub fn global_loader() -> &'static DynamicLoader {
    GLOBAL_LOADER.get_or_init(DynamicLoader::new)
}

/// Load a tree-sitter grammar dynamically from a shared library.
///
/// This function loads a compiled tree-sitter grammar (.so, .dylib, or .dll)
/// and returns the Language object.
///
/// # Safety
/// This function uses `unsafe` to interface with dynamic libraries.
/// The loaded library must be a valid tree-sitter grammar.
///
/// # Arguments
/// * `name` - The language name/identifier
/// * `path` - Path to the compiled grammar library
///
/// # Returns
/// The Language on success, or RegistryError if loading fails.
pub fn load_dynamic_grammar(_name: &str, _path: &Path) -> Result<Language, RegistryError> {
    // This is a stub implementation that always returns an error
    // The full implementation would use libloading to load the shared library
    // and call the tree-sitter grammar's language() function
    
    // For now, we just return an error indicating this isn't fully implemented
    Err(RegistryError::DynamicLoadingDisabled)
}

/// Register a pre-loaded language with the dynamic loader.
///
/// This is useful for testing or when you have a language loaded through
/// other means.
pub fn register_preloaded_language(name: &str, language: Language, path: Option<String>) {
    let loader = global_loader();
    loader.store_grammar(name.to_string(), language, path);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_global_loader() {
        let loader1 = global_loader();
        let loader2 = global_loader();
        // Both should point to the same instance
        assert!(loader1.is_loaded("nonexistent") == loader2.is_loaded("nonexistent"));
    }

    #[test]
    fn test_empty_loader() {
        let loader = DynamicLoader::new();
        assert!(!loader.is_loaded("any"));
        assert!(loader.get_grammar("any").is_none());
        assert!(loader.list_loaded().is_empty());
    }

    #[test]
    fn test_unload_grammar() {
        let loader = DynamicLoader::new();
        
        // Unload non-existent should not panic
        loader.unload_grammar("nonexistent");
        
        assert!(!loader.is_loaded("nonexistent"));
    }

    #[test]
    fn test_load_dynamic_grammar_returns_error() {
        // The stub implementation should return an error
        let result = load_dynamic_grammar("test", Path::new("/nonexistent/path.so"));
        assert!(result.is_err());
    }
}
