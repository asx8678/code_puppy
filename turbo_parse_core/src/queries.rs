//! Tree-sitter query loader module.
//!
//! This module provides functions to load tree-sitter query files
//! vendored from the Helix Editor project. Queries are embedded at
//! compile time using `include_str!` for performance.

use crate::types::{QueryError, QueryType};
use std::collections::HashMap;

/// Get the highlights query for a language.
///
/// # Arguments
/// * `language` - The language name (e.g., "python", "rust", "javascript")
///
/// # Returns
/// The query string or an error if the language is not supported.
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
pub fn normalize_language(language: &str) -> String {
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

// Python queries - vendored from Helix Editor
const PYTHON_HIGHLIGHTS: &str = include_str!("../../turbo_parse/queries/python/highlights.scm");
const PYTHON_FOLDS: &str = include_str!("../../turbo_parse/queries/python/folds.scm");
const PYTHON_INDENTS: &str = include_str!("../../turbo_parse/queries/python/indents.scm");

// Rust queries - vendored from Helix Editor
const RUST_HIGHLIGHTS: &str = include_str!("../../turbo_parse/queries/rust/highlights.scm");
const RUST_FOLDS: &str = include_str!("../../turbo_parse/queries/rust/folds.scm");
const RUST_INDENTS: &str = include_str!("../../turbo_parse/queries/rust/indents.scm");

// JavaScript queries - vendored from Helix Editor
const JAVASCRIPT_HIGHLIGHTS: &str = include_str!("../../turbo_parse/queries/javascript/highlights.scm");
const JAVASCRIPT_FOLDS: &str = include_str!("../../turbo_parse/queries/javascript/folds.scm");
const JAVASCRIPT_INDENTS: &str = include_str!("../../turbo_parse/queries/javascript/indents.scm");

// TypeScript queries - vendored from Helix Editor
const TYPESCRIPT_HIGHLIGHTS: &str = include_str!("../../turbo_parse/queries/typescript/highlights.scm");
const TYPESCRIPT_FOLDS: &str = include_str!("../../turbo_parse/queries/typescript/folds.scm");
const TYPESCRIPT_INDENTS: &str = include_str!("../../turbo_parse/queries/typescript/indents.scm");

// TSX queries - vendored from Helix Editor
const TSX_HIGHLIGHTS: &str = include_str!("../../turbo_parse/queries/tsx/highlights.scm");
const TSX_FOLDS: &str = include_str!("../../turbo_parse/queries/tsx/folds.scm");
const TSX_INDENTS: &str = include_str!("../../turbo_parse/queries/tsx/indents.scm");

// Elixir queries - vendored from Helix Editor
const ELIXIR_HIGHLIGHTS: &str = include_str!("../../turbo_parse/queries/elixir/highlights.scm");
const ELIXIR_FOLDS: &str = include_str!("../../turbo_parse/queries/elixir/folds.scm");
const ELIXIR_INDENTS: &str = include_str!("../../turbo_parse/queries/elixir/indents.scm");

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
        use std::str::FromStr;

        assert_eq!(
            QueryType::from_str("highlights").unwrap(),
            QueryType::Highlights
        );
        assert_eq!(
            QueryType::from_str("folds").unwrap(),
            QueryType::Folds
        );
        assert_eq!(
            QueryType::from_str("indents").unwrap(),
            QueryType::Indents
        );
        assert!(QueryType::from_str("unknown").is_err());
    }
}
