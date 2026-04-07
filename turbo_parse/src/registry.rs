//! Language Registry — Static storage for tree-sitter grammars.
//!
//! Provides lazy-initialized access to tree-sitter Language objects
//! for Python, Rust, JavaScript, TypeScript, TSX, and Elixir.

use std::collections::HashMap;
use std::sync::OnceLock;
use tree_sitter::Language;

/// Errors that can occur when working with the language registry.
#[derive(Debug, Clone, PartialEq)]
pub enum RegistryError {
    /// The requested language is not supported.
    UnsupportedLanguage(String),
    /// Failed to initialize the language grammar.
    InitializationError(String),
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
    pub fn get(&self, name: &str) -> Result<&Language, RegistryError> {
        let normalized = name.to_lowercase();

        // Handle aliases
        let key = match normalized.as_str() {
            "js" => "javascript",
            "ts" => "typescript",
            "ex" => "elixir",
            _ => &normalized,
        };

        self.languages
            .get(key)
            .ok_or_else(|| RegistryError::UnsupportedLanguage(name.to_string()))
    }

    /// Check if a language is supported.
    pub fn is_supported(&self, name: &str) -> bool {
        self.get(name).is_ok()
    }

    /// Get a list of all supported language names.
    pub fn supported_languages(&self) -> Vec<String> {
        self.languages.keys().cloned().collect()
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

/// Get the global language registry instance.
///
/// The registry is initialized lazily on first access.
pub fn global_registry() -> &'static LanguageRegistry {
    GLOBAL_REGISTRY.get_or_init(LanguageRegistry::default)
}

/// Get a language by name using the global registry.
///
/// This is the convenience function exposed to Python.
pub fn get_language(name: &str) -> Result<&'static Language, RegistryError> {
    global_registry().get(name)
}

/// Check if a language is supported.
pub fn is_language_supported(name: &str) -> bool {
    global_registry().is_supported(name)
}

/// Get all supported language names.
pub fn list_supported_languages() -> Vec<String> {
    global_registry().supported_languages()
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
        assert_eq!(lang.version(), tree_sitter_python::LANGUAGE.version());
    }

    #[test]
    fn test_get_rust() {
        let registry = LanguageRegistry::new().unwrap();
        let lang = registry.get("rust").unwrap();
        assert_eq!(lang.version(), tree_sitter_rust::LANGUAGE.version());
    }

    #[test]
    fn test_get_javascript() {
        let registry = LanguageRegistry::new().unwrap();
        let lang = registry.get("javascript").unwrap();
        assert_eq!(lang.version(), tree_sitter_javascript::LANGUAGE.version());
    }

    #[test]
    fn test_get_typescript() {
        let registry = LanguageRegistry::new().unwrap();
        let lang = registry.get("typescript").unwrap();
        assert!(lang.version().len() > 0);
    }

    #[test]
    fn test_get_tsx() {
        let registry = LanguageRegistry::new().unwrap();
        let lang = registry.get("tsx").unwrap();
        assert!(lang.version().len() > 0);
    }

    #[test]
    fn test_get_elixir() {
        let registry = LanguageRegistry::new().unwrap();
        let lang = registry.get("elixir").unwrap();
        assert_eq!(lang.version(), tree_sitter_elixir::LANGUAGE.version());
    }

    #[test]
    fn test_language_aliases() {
        let registry = LanguageRegistry::new().unwrap();

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
        assert!(lang.version().len() > 0);

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
}
