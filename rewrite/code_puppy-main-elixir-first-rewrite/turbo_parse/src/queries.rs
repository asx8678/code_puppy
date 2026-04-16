//! Tree-sitter query loader module.
//!
//! This module provides functions to load tree-sitter query files
//! vendored from the Helix Editor project. Queries are embedded at
//! compile time using `include_str!` for performance.
//!
//! # Supported Languages
//! - Python
//! - Rust
//! - JavaScript
//! - TypeScript
//! - TSX
//! - Elixir
//!
//! # Query Types
//! - `highlights` - Syntax highlighting queries
//! - `folds` - Code folding queries
//! - `indents` - Smart indentation queries

use std::collections::HashMap;

/// Errors that can occur when loading queries.
#[derive(Debug, Clone, PartialEq)]
pub enum QueryError {
    /// The specified language is not supported.
    UnsupportedLanguage(String),
    /// The specified query type is not available for this language.
    QueryTypeNotAvailable { language: String, query_type: String },
}

impl std::fmt::Display for QueryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            QueryError::UnsupportedLanguage(lang) => {
                write!(f, "Unsupported language: '{}'", lang)
            }
            QueryError::QueryTypeNotAvailable { language, query_type } => {
                write!(
                    f,
                    "Query type '{}' not available for language '{}'",
                    query_type, language
                )
            }
        }
    }
}

impl std::error::Error for QueryError {}

/// Query types supported for syntax analysis.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum QueryType {
    /// Syntax highlighting queries.
    Highlights,
    /// Code folding queries.
    Folds,
    /// Smart indentation queries.
    Indents,
}

impl QueryType {
    /// Returns the file name for this query type.
    pub fn as_str(&self) -> &'static str {
        match self {
            QueryType::Highlights => "highlights.scm",
            QueryType::Folds => "folds.scm",
            QueryType::Indents => "indents.scm",
        }
    }
}

impl std::fmt::Display for QueryType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

impl std::str::FromStr for QueryType {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "highlights" | "highlight" => Ok(QueryType::Highlights),
            "folds" | "fold" => Ok(QueryType::Folds),
            "indents" | "indent" => Ok(QueryType::Indents),
            _ => Err(format!("Unknown query type: {}", s)),
        }
    }
}

/// Get the highlights query for a language.
///
/// # Arguments
/// * `language` - The language name (e.g., "python", "rust", "javascript")
///
/// # Returns
/// The query string or an error if the language is not supported.
///
/// # Example
/// ```rust
/// use turbo_parse::queries::get_highlights_query;
///
/// let query = get_highlights_query("python").unwrap();
/// assert!(query.contains("function"));
/// ```
pub fn get_highlights_query(language: &str) -> Result<&'static str, QueryError> {
    get_query(language, QueryType::Highlights)
}

/// Get the folds query for a language.
///
/// # Arguments
/// * `language` - The language name (e.g., "python", "rust", "javascript")
///
/// # Returns
/// The query string or an error if the language/query is not available.
pub fn get_folds_query(language: &str) -> Result<&'static str, QueryError> {
    get_query(language, QueryType::Folds)
}

/// Get the indents query for a language.
///
/// # Arguments
/// * `language` - The language name (e.g., "python", "rust", "javascript")
///
/// # Returns
/// The query string or an error if the language/query is not available.
pub fn get_indents_query(language: &str) -> Result<&'static str, QueryError> {
    get_query(language, QueryType::Indents)
}

/// Get a query by language and type.
///
/// # Arguments
/// * `language` - The language name (normalized internally)
/// * `query_type` - The type of query to load
///
/// # Returns
/// The query string or an error if not available.
pub fn get_query(
    language: &str,
    query_type: QueryType,
) -> Result<&'static str, QueryError> {
    let normalized = normalize_language(language);

    match (normalized.as_str(), query_type) {
        // Python
        ("python", QueryType::Highlights) => Ok(PYTHON_HIGHLIGHTS),
        ("python", QueryType::Folds) => Ok(PYTHON_FOLDS),
        ("python", QueryType::Indents) => Ok(PYTHON_INDENTS),

        // Rust
        ("rust", QueryType::Highlights) => Ok(RUST_HIGHLIGHTS),
        ("rust", QueryType::Folds) => Ok(RUST_FOLDS),
        ("rust", QueryType::Indents) => Ok(RUST_INDENTS),

        // JavaScript
        ("javascript", QueryType::Highlights) => Ok(JAVASCRIPT_HIGHLIGHTS),
        ("javascript", QueryType::Folds) => Ok(JAVASCRIPT_FOLDS),
        ("javascript", QueryType::Indents) => Ok(JAVASCRIPT_INDENTS),

        // TypeScript
        ("typescript", QueryType::Highlights) => Ok(TYPESCRIPT_HIGHLIGHTS),
        ("typescript", QueryType::Folds) => Ok(TYPESCRIPT_FOLDS),
        ("typescript", QueryType::Indents) => Ok(TYPESCRIPT_INDENTS),

        // TSX
        ("tsx", QueryType::Highlights) => Ok(TSX_HIGHLIGHTS),
        ("tsx", QueryType::Folds) => Ok(TSX_FOLDS),
        ("tsx", QueryType::Indents) => Ok(TSX_INDENTS),

        // Elixir
        ("elixir", QueryType::Highlights) => Ok(ELIXIR_HIGHLIGHTS),
        ("elixir", QueryType::Folds) => Ok(ELIXIR_FOLDS),
        ("elixir", QueryType::Indents) => Ok(ELIXIR_INDENTS),

        // Unsupported language
        _ => Err(QueryError::UnsupportedLanguage(language.to_string())),
    }
}

/// Normalize a language name to our supported set.
fn normalize_language(language: &str) -> String {
    match language.to_lowercase().as_str() {
        "py" => "python".to_string(),
        "js" => "javascript".to_string(),
        "ts" => "typescript".to_string(),
        "jsx" => "javascript".to_string(),
        "ex" | "exs" => "elixir".to_string(),
        other => other.to_string(),
    }
}

/// Returns a list of all supported languages.
pub fn supported_languages() -> Vec<&'static str> {
    vec!["python", "rust", "javascript", "typescript", "tsx", "elixir"]
}

/// Returns a map of available query types for each language.
pub fn available_queries() -> HashMap<&'static str, Vec<QueryType>> {
    let mut map = HashMap::new();
    let all_types = vec![QueryType::Highlights, QueryType::Folds, QueryType::Indents];

    for lang in supported_languages() {
        map.insert(lang, all_types.clone());
    }

    map
}

/// Check if a language is supported.
pub fn is_language_supported(language: &str) -> bool {
    let normalized = normalize_language(language);
    supported_languages().iter().any(|&lang| lang == normalized.as_str())
}

/// Get information about available queries for a language.
pub fn get_language_info(language: &str) -> Option<LanguageInfo> {
    let normalized = normalize_language(language);

    if !is_language_supported(language) {
        return None;
    }

    Some(LanguageInfo {
        name: normalized,
        highlights_available: true,
        folds_available: true,
        indents_available: true,
    })
}

/// Information about available queries for a language.
#[derive(Debug, Clone)]
pub struct LanguageInfo {
    /// The normalized language name.
    pub name: String,
    /// Whether highlights queries are available.
    pub highlights_available: bool,
    /// Whether folds queries are available.
    pub folds_available: bool,
    /// Whether indents queries are available.
    pub indents_available: bool,
}

// =============================================================================
// Embedded Query Files
// =============================================================================

// Python queries
const PYTHON_HIGHLIGHTS: &str = include_str!("../queries/python/highlights.scm");
const PYTHON_FOLDS: &str = include_str!("../queries/python/folds.scm");
const PYTHON_INDENTS: &str = include_str!("../queries/python/indents.scm");

// Rust queries
const RUST_HIGHLIGHTS: &str = include_str!("../queries/rust/highlights.scm");
const RUST_FOLDS: &str = include_str!("../queries/rust/folds.scm");
const RUST_INDENTS: &str = include_str!("../queries/rust/indents.scm");

// JavaScript queries
const JAVASCRIPT_HIGHLIGHTS: &str = include_str!("../queries/javascript/highlights.scm");
const JAVASCRIPT_FOLDS: &str = include_str!("../queries/javascript/folds.scm");
const JAVASCRIPT_INDENTS: &str = include_str!("../queries/javascript/indents.scm");

// TypeScript queries
const TYPESCRIPT_HIGHLIGHTS: &str = include_str!("../queries/typescript/highlights.scm");
const TYPESCRIPT_FOLDS: &str = include_str!("../queries/typescript/folds.scm");
const TYPESCRIPT_INDENTS: &str = include_str!("../queries/typescript/indents.scm");

// TSX queries
const TSX_HIGHLIGHTS: &str = include_str!("../queries/tsx/highlights.scm");
const TSX_FOLDS: &str = include_str!("../queries/tsx/folds.scm");
const TSX_INDENTS: &str = include_str!("../queries/tsx/indents.scm");

// Elixir queries
const ELIXIR_HIGHLIGHTS: &str = include_str!("../queries/elixir/highlights.scm");
const ELIXIR_FOLDS: &str = include_str!("../queries/elixir/folds.scm");
const ELIXIR_INDENTS: &str = include_str!("../queries/elixir/indents.scm");

// =============================================================================
// Tests
// =============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_language() {
        assert_eq!(normalize_language("python"), "python");
        assert_eq!(normalize_language("py"), "python");
        assert_eq!(normalize_language("PY"), "python");
        assert_eq!(normalize_language("js"), "javascript");
        assert_eq!(normalize_language("ts"), "typescript");
        assert_eq!(normalize_language("ex"), "elixir");
    }

    #[test]
    fn test_get_highlights_query() {
        let python_query = get_highlights_query("python").unwrap();
        assert!(!python_query.is_empty());
        assert!(python_query.contains("Source: Helix Editor"));

        let rust_query = get_highlights_query("rust").unwrap();
        assert!(!rust_query.is_empty());

        // Test unsupported language
        assert!(get_highlights_query("unsupported_lang").is_err());
    }

    #[test]
    fn test_get_folds_query() {
        let python_query = get_folds_query("python").unwrap();
        assert!(!python_query.is_empty());
    }

    #[test]
    fn test_get_indents_query() {
        let python_query = get_indents_query("python").unwrap();
        assert!(!python_query.is_empty());
    }

    #[test]
    fn test_get_query_by_type() {
        let highlights = get_query("python", QueryType::Highlights).unwrap();
        let folds = get_query("python", QueryType::Folds).unwrap();
        let indents = get_query("python", QueryType::Indents).unwrap();

        assert_ne!(highlights, folds);
        assert!(!highlights.is_empty());
        assert!(!folds.is_empty());
        assert!(!indents.is_empty());
    }

    #[test]
    fn test_supported_languages() {
        let langs = supported_languages();
        assert!(langs.contains(&"python"));
        assert!(langs.contains(&"rust"));
        assert!(langs.contains(&"javascript"));
        assert!(langs.contains(&"typescript"));
        assert!(langs.contains(&"tsx"));
        assert!(langs.contains(&"elixir"));
    }

    #[test]
    fn test_is_language_supported() {
        assert!(is_language_supported("python"));
        assert!(is_language_supported("py"));
        assert!(is_language_supported("rust"));
        assert!(is_language_supported("javascript"));
        assert!(is_language_supported("js"));
        assert!(!is_language_supported("unsupported"));
    }

    #[test]
    fn test_get_language_info() {
        let info = get_language_info("python").unwrap();
        assert_eq!(info.name, "python");
        assert!(info.highlights_available);
        assert!(info.folds_available);
        assert!(info.indents_available);

        assert!(get_language_info("unsupported").is_none());
    }

    #[test]
    fn test_all_queries_loadable() {
        // Ensure all supported languages have all query types available
        for lang in supported_languages() {
            assert!(
                get_highlights_query(lang).is_ok(),
                "Highlights query should load for {}",
                lang
            );
            assert!(
                get_folds_query(lang).is_ok(),
                "Folds query should load for {}",
                lang
            );
            assert!(
                get_indents_query(lang).is_ok(),
                "Indents query should load for {}",
                lang
            );
        }
    }

    #[test]
    fn test_query_type_from_str() {
        assert_eq!(
            "highlights".parse::<QueryType>().unwrap(),
            QueryType::Highlights
        );
        assert_eq!("folds".parse::<QueryType>().unwrap(), QueryType::Folds);
        assert_eq!("indents".parse::<QueryType>().unwrap(), QueryType::Indents);
        assert!("unknown".parse::<QueryType>().is_err());
    }

    #[test]
    fn test_query_error_display() {
        let err = QueryError::UnsupportedLanguage("foo".to_string());
        assert!(err.to_string().contains("foo"));

        let err = QueryError::QueryTypeNotAvailable {
            language: "bar".to_string(),
            query_type: "baz".to_string(),
        };
        assert!(err.to_string().contains("bar"));
        assert!(err.to_string().contains("baz"));
    }
}
