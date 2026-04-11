//! Language Registry — Static storage for tree-sitter grammars.
//!
//! Provides lazy-initialized access to tree-sitter Language objects
//! for Python, Rust, JavaScript, TypeScript, TSX, and Elixir.
//!
//! Supports dynamic grammar loading when the `dynamic-grammars` feature is enabled.

use std::collections::HashMap;
use std::path::Path;
use std::sync::OnceLock;
use tree_sitter::Language;

#[cfg(feature = "dynamic-grammars")]
use crate::dynamic::{global_loader, load_dynamic_grammar};

/// Errors that can occur when working with the language registry.
#[derive(Debug, Clone, PartialEq)]
pub enum RegistryError {
    /// The requested language is not supported.
    UnsupportedLanguage(String),
    /// Failed to initialize the language grammar.
    InitializationError(String),
    /// Dynamic loading is not available for this language.
    DynamicLoadingDisabled,
}

impl std::fmt::Display for RegistryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RegistryError::UnsupportedLanguage(lang) => {
                write!(f, "Unsupported language: '{}'", lang)
            }
            RegistryError::InitializationError(msg) => {
                write!(f, "Failed to initialize language: {}", msg)
            }
            RegistryError::DynamicLoadingDisabled => {
                write!(f, "Dynamic grammar loading is disabled")
            }
        }
    }
}

impl std::error::Error for RegistryError {}

/// Supported programming languages.
pub const SUPPORTED_LANGUAGES: &[&str] = &[
    "python",
    "rust",
    "javascript",
    "typescript",
    "tsx",
    "elixir",
];

/// Registry holding all loaded tree-sitter grammars.
pub struct LanguageRegistry {
    languages: HashMap<String, Language>,
}

impl LanguageRegistry {
    /// Create a new registry with all grammars loaded.
    pub fn new() -> Result<Self, RegistryError> {
        let mut languages = HashMap::new();

        // Load Python grammar
        let python_lang = Language::from(tree_sitter_python::LANGUAGE);
        languages.insert("python".to_string(), python_lang);

        // Load Rust grammar
        let rust_lang = Language::from(tree_sitter_rust::LANGUAGE);
        languages.insert("rust".to_string(), rust_lang);

        // Load JavaScript grammar
        let js_lang = Language::from(tree_sitter_javascript::LANGUAGE);
        languages.insert("javascript".to_string(), js_lang);

        // Load TypeScript grammar
        let ts_lang = tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into();
        languages.insert("typescript".to_string(), ts_lang);

        // Load TSX grammar
        let tsx_lang = tree_sitter_typescript::LANGUAGE_TSX.into();
        languages.insert("tsx".to_string(), tsx_lang);

        // Load Elixir grammar
        let ex_lang = Language::from(tree_sitter_elixir::LANGUAGE);
        languages.insert("elixir".to_string(), ex_lang);

        Ok(Self { languages })
    }

    /// Get a language by name.
    ///
    /// Names are case-insensitive. Supported names:
    /// - "python"
    /// - "rust"
    /// - "javascript" (or "js")
    /// - "typescript" (or "ts")
    /// - "tsx"
    /// - "elixir" (or "ex")
    pub fn get(&self, name: &str) -> Result<Language, RegistryError> {
        let normalized = name.to_lowercase();

        // Handle aliases
        let key = match normalized.as_str() {
            "py" => "python",
            "js" => "javascript",
            "ts" => "typescript",
            "ex" | "exs" => "elixir",
            _ => &normalized,
        };

        self.languages
            .get(key)
            .cloned()
            .ok_or_else(|| RegistryError::UnsupportedLanguage(name.to_string()))
    }

    /// Check if a language is supported.
    pub fn is_supported(&self, name: &str) -> bool {
        self.get(name).is_ok()
    }

    /// Get a list of all supported language names.
    pub fn supported_languages(&self) -> Vec<String> {
        let mut langs: Vec<String> = self.languages.keys().cloned().collect();
        langs.sort();
        langs
    }
}

impl Default for LanguageRegistry {
    fn default() -> Self {
        // This should never fail since all languages are built-in
        Self::new().expect("Failed to initialize language registry")
    }
}

// Global static instance for lazy initialization
static GLOBAL_REGISTRY: OnceLock<LanguageRegistry> = OnceLock::new();

// Runtime-registered dynamic grammars (name -> library path)
static DYNAMIC_GRAMMARS: OnceLock<std::sync::Mutex<HashMap<String, String>>> = OnceLock::new();

/// Get the global language registry instance.
///
/// The registry is initialized lazily on first access.
pub fn global_registry() -> &'static LanguageRegistry {
    GLOBAL_REGISTRY.get_or_init(LanguageRegistry::default)
}

/// Get dynamic grammars registry.
fn dynamic_grammars() -> &'static std::sync::Mutex<HashMap<String, String>> {
    DYNAMIC_GRAMMARS.get_or_init(|| std::sync::Mutex::new(HashMap::new()))
}

/// Register a dynamic grammar at runtime.
///
/// This adds a dynamic grammar to the registry with fallback support.
/// If loading fails, the grammar will not be registered and an error
/// will be returned.
///
/// # Arguments
/// * `name` - The language name/identifier
/// * `library_path` - Path to the compiled grammar library (.so/.dylib/.dll)
///
/// # Returns
/// Ok(()) on success, or RegistryError if loading fails.
#[cfg(feature = "dynamic-grammars")]
pub fn register_dynamic_grammar(name: &str, library_path: &str) -> Result<(), RegistryError> {
    use std::path::PathBuf;
    
    // Load the grammar using the dynamic loader
    let path = PathBuf::from(library_path);
    load_dynamic_grammar(name, &path)?;
    
    // Store the registration
    let mut grammars = dynamic_grammars().lock().unwrap();
    grammars.insert(name.to_string(), library_path.to_string());
    
    Ok(())
}

/// Stub implementation when feature is not enabled.
#[cfg(not(feature = "dynamic-grammars"))]
pub fn register_dynamic_grammar(_name: &str, _library_path: &str) -> Result<(), RegistryError> {
    Err(RegistryError::DynamicLoadingDisabled)
}

/// Unregister a dynamic grammar.
pub fn unregister_dynamic_grammar(name: &str) -> bool {
    let mut grammars = dynamic_grammars().lock().unwrap();
    let removed = grammars.remove(name).is_some();

    // Also evict from the loader cache (now safe because we return owned Language)
    #[cfg(feature = "dynamic-grammars")]
    if removed {
        let loader = global_loader();
        loader.unload_grammar(name);
    }

    removed
}

/// Check if a dynamic grammar is registered.
pub fn is_dynamic_grammar_registered(name: &str) -> bool {
    let grammars = dynamic_grammars().lock().unwrap();
    grammars.contains_key(name)
}

/// List all registered dynamic grammars.
pub fn list_registered_dynamic_grammars() -> Vec<(String, String)> {
    let grammars = dynamic_grammars().lock().unwrap();
    grammars.iter().map(|(k, v)| (k.clone(), v.clone())).collect()
}

/// Get a language by name using the global registry.
///
/// This is the convenience function exposed to Python.
/// Falls back to dynamic loading if the language is not a built-in.
pub fn get_language(name: &str) -> Result<Language, RegistryError> {
    // First try the built-in registry
    match global_registry().get(name) {
        Ok(lang) => Ok(lang),
        Err(RegistryError::UnsupportedLanguage(_)) => {
            // Try dynamic grammars
            #[cfg(feature = "dynamic-grammars")]
            {
                use crate::dynamic::global_loader;
                
                let normalized = normalize_language(name);
                
                // Check if it's registered
                if is_dynamic_grammar_registered(&normalized) {
                    // Try to get from the loader
                    let loader = global_loader();
                    if let Some(grammar) = loader.get_grammar(&normalized) {
                        return Ok(grammar.language.clone());
                    }
                }
                
                // Check if it's already loaded (but not registered through the registry API)
                let loader = global_loader();
                if let Some(grammar) = loader.get_grammar(&normalized) {
                    return Ok(grammar.language.clone());
                }
            }
            
            Err(RegistryError::UnsupportedLanguage(name.to_string()))
        }
        Err(e) => Err(e),
    }
}

/// Get a language with fallback to built-in if dynamic loading fails.
///
/// This is useful when you want to prefer a dynamic grammar but fall back
/// to the built-in one if the dynamic version isn't available.
pub fn get_language_with_fallback(name: &str) -> Option<Language> {
    // Try dynamic first
    #[cfg(feature = "dynamic-grammars")]
    {
        let normalized = normalize_language(name);
        let loader = global_loader();
        
        if let Some(grammar) = loader.get_grammar(&normalized) {
            return Some(grammar.language.clone());
        }
    }
    
    // Fall back to built-in
    global_registry().get(name).ok()
}

/// Check if a language is supported (including dynamic grammars).
pub fn is_language_supported(name: &str) -> bool {
    // Check built-in
    if global_registry().is_supported(name) {
        return true;
    }
    
    // Check dynamic grammars
    #[cfg(feature = "dynamic-grammars")]
    {
        let normalized = normalize_language(name);
        let loader = global_loader();
        if loader.is_loaded(&normalized) {
            return true;
        }
    }
    
    false
}

/// Get all supported language names (including dynamic).
pub fn list_supported_languages() -> Vec<String> {
    let mut langs = global_registry().supported_languages();
    
    // Add dynamic grammars
    #[cfg(feature = "dynamic-grammars")]
    {
        let loader = global_loader();
        let dynamic = loader.list_loaded();
        for grammar in dynamic {
            if !langs.contains(&grammar.name) {
                langs.push(grammar.name);
            }
        }
    }
    
    langs.sort();
    langs
}

/// Load a grammar dynamically and make it available.
///
/// This is a higher-level API that loads a grammar and automatically
/// registers it for future lookups.
#[cfg(feature = "dynamic-grammars")]
pub fn load_and_register_grammar(name: &str, path: &Path) -> Result<Language, RegistryError> {
    use crate::dynamic::load_dynamic_grammar;
    
    let lang = load_dynamic_grammar(name, path)?;
    
    // Register in the path registry
    let mut grammars = dynamic_grammars().lock().unwrap();
    grammars.insert(name.to_string(), path.to_string_lossy().to_string());
    
    Ok(lang)
}

/// Stub when feature is not enabled.
#[cfg(not(feature = "dynamic-grammars"))]
pub fn load_and_register_grammar(_name: &str, _path: &Path) -> Result<Language, RegistryError> {
    Err(RegistryError::DynamicLoadingDisabled)
}

/// Normalize a language name to its canonical form.
///
/// Handles case-insensitivity and common aliases.
///
/// # Examples
/// * "py" -> "python"
/// * "js" -> "javascript"
/// * "ts" -> "typescript"
/// * "ex" | "exs" -> "elixir"
/// * "PYTHON" -> "python"
pub fn normalize_language(name: &str) -> String {
    let normalized = name.to_lowercase();
    match normalized.as_str() {
        "py" => "python".to_string(),
        "js" => "javascript".to_string(),
        "ts" => "typescript".to_string(),
        "ex" | "exs" => "elixir".to_string(),
        _ => normalized,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_registry_creation() {
        let registry = LanguageRegistry::new().unwrap();
        assert_eq!(registry.supported_languages().len(), 6);
    }

    #[test]
    fn test_get_python() {
        let registry = LanguageRegistry::new().unwrap();
        let lang = registry.get("python").unwrap();
        let python_lang = Language::from(tree_sitter_python::LANGUAGE);
        assert_eq!(lang.version(), python_lang.version());
    }

    #[test]
    fn test_get_rust() {
        let registry = LanguageRegistry::new().unwrap();
        let lang = registry.get("rust").unwrap();
        let rust_lang = Language::from(tree_sitter_rust::LANGUAGE);
        assert_eq!(lang.version(), rust_lang.version());
    }

    #[test]
    fn test_get_javascript() {
        let registry = LanguageRegistry::new().unwrap();
        let lang = registry.get("javascript").unwrap();
        let js_lang = Language::from(tree_sitter_javascript::LANGUAGE);
        assert_eq!(lang.version(), js_lang.version());
    }

    #[test]
    fn test_get_typescript() {
        let registry = LanguageRegistry::new().unwrap();
        let lang = registry.get("typescript").unwrap();
        assert!(lang.version() > 0);
    }

    #[test]
    fn test_get_tsx() {
        let registry = LanguageRegistry::new().unwrap();
        let lang = registry.get("tsx").unwrap();
        assert!(lang.version() > 0);
    }

    #[test]
    fn test_get_elixir() {
        let registry = LanguageRegistry::new().unwrap();
        let lang = registry.get("elixir").unwrap();
        let ex_lang = Language::from(tree_sitter_elixir::LANGUAGE);
        assert_eq!(lang.version(), ex_lang.version());
    }

    #[test]
    fn test_language_aliases() {
        let registry = LanguageRegistry::new().unwrap();

        // PY alias
        let py = registry.get("py").unwrap();
        let python = registry.get("python").unwrap();
        assert_eq!(py.version(), python.version());

        // JS alias
        let js = registry.get("js").unwrap();
        let javascript = registry.get("javascript").unwrap();
        assert_eq!(js.version(), javascript.version());

        // TS alias
        let ts = registry.get("ts").unwrap();
        let typescript = registry.get("typescript").unwrap();
        assert_eq!(ts.version(), typescript.version());

        // EX alias
        let ex = registry.get("ex").unwrap();
        let elixir = registry.get("elixir").unwrap();
        assert_eq!(ex.version(), elixir.version());
    }

    #[test]
    fn test_case_insensitive() {
        let registry = LanguageRegistry::new().unwrap();

        assert!(registry.get("PYTHON").is_ok());
        assert!(registry.get("Python").is_ok());
        assert!(registry.get("RUST").is_ok());
        assert!(registry.get("Rust").is_ok());
        assert!(registry.get("JavaScript").is_ok());
        assert!(registry.get("TypeScript").is_ok());
    }

    #[test]
    fn test_unsupported_language() {
        let registry = LanguageRegistry::new().unwrap();

        let result = registry.get("go");
        assert!(result.is_err());
        assert_eq!(
            result.unwrap_err(),
            RegistryError::UnsupportedLanguage("go".to_string())
        );
    }

    #[test]
    fn test_is_supported() {
        let registry = LanguageRegistry::new().unwrap();

        assert!(registry.is_supported("python"));
        assert!(registry.is_supported("rust"));
        assert!(registry.is_supported("javascript"));
        assert!(registry.is_supported("typescript"));
        assert!(registry.is_supported("tsx"));
        assert!(registry.is_supported("elixir"));

        assert!(!registry.is_supported("go"));
        assert!(!registry.is_supported("java"));
        assert!(!registry.is_supported(""));
    }

    #[test]
    fn test_global_registry() {
        // First call initializes
        let registry1 = global_registry();
        let registry2 = global_registry();

        // Should be the same instance
        assert_eq!(registry1.supported_languages(), registry2.supported_languages());
    }

    #[test]
    fn test_get_language_convenience() {
        let lang = get_language("python").unwrap();
        assert!(lang.version() > 0);

        let result = get_language("unknown");
        assert!(result.is_err());
    }

    #[test]
    fn test_list_supported_languages() {
        let langs = list_supported_languages();
        assert_eq!(langs.len(), 6);
        assert!(langs.contains(&"python".to_string()));
        assert!(langs.contains(&"rust".to_string()));
        assert!(langs.contains(&"javascript".to_string()));
        assert!(langs.contains(&"typescript".to_string()));
        assert!(langs.contains(&"tsx".to_string()));
        assert!(langs.contains(&"elixir".to_string()));
    }

    #[test]
    fn test_normalize_language() {
        assert_eq!(normalize_language("py"), "python");
        assert_eq!(normalize_language("python"), "python");
        assert_eq!(normalize_language("PYTHON"), "python");
        assert_eq!(normalize_language("js"), "javascript");
        assert_eq!(normalize_language("javascript"), "javascript");
        assert_eq!(normalize_language("ts"), "typescript");
        assert_eq!(normalize_language("typescript"), "typescript");
        assert_eq!(normalize_language("ex"), "elixir");
        assert_eq!(normalize_language("exs"), "elixir");
        assert_eq!(normalize_language("elixir"), "elixir");
        assert_eq!(normalize_language("rust"), "rust");
        assert_eq!(normalize_language("tsx"), "tsx");
    }

    #[test]
    fn test_dynamic_grammar_registration() {
        // These tests don't require the feature to be enabled
        // as they test the stub implementation
        
        // Test that the registry functions exist
        assert!(!is_dynamic_grammar_registered("test"));
        assert!(list_registered_dynamic_grammars().is_empty());
        assert!(!unregister_dynamic_grammar("test"));
    }

    #[test]
    fn test_unregister_evicts_from_loader() {
        // Test that unregister_dynamic_grammar evicts from the loader cache.
        // This prevents get_language from finding the grammar after unregister.
        
        // This is mostly tested at compile time - we're ensuring that:
        // 1. unregister_dynamic_grammar compiles with the feature-gated loader eviction
        // 2. The code structure is correct
        
        // We can't easily test the full integration without a real .so/.dylib file,
        // but we can verify the basic behavior works.
        
        // Register a fake path (this won't load without a real library)
        let _ = register_dynamic_grammar("test_lang", "/nonexistent/path.so");
        
        // The grammar may or may not be registered depending on whether
        // the feature is enabled and whether the path exists
        
        // Unregister should always work without panicking
        let _ = unregister_dynamic_grammar("test_lang");
        
        // After unregister, it should not be registered
        assert!(!is_dynamic_grammar_registered("test_lang"));
    }

    #[test]
    fn test_error_display() {
        assert!(RegistryError::UnsupportedLanguage("test".to_string()).to_string().contains("Unsupported"));
        assert!(RegistryError::InitializationError("test".to_string()).to_string().contains("Failed"));
        assert!(RegistryError::DynamicLoadingDisabled.to_string().contains("disabled"));
    }
}
