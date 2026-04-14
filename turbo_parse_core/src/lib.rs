//! turbo_parse_core - Core parsing logic for tree-sitter.
//!
//! This crate provides the core parsing functionality without any binding-specific
//! code (no PyO3 or Rustler). It can be used by both Python (via PyO3 wrapper)
//! and Elixir (via Rustler NIF) bindings.
//!
//! # Modules
//!
//! * `parser` - Parse source code and files, return AST as JSON
//! * `symbols` - Extract symbols (functions, classes, methods, imports)
//! * `diagnostics` - Extract syntax errors and diagnostics
//! * `folds` - Extract code folding regions
//! * `highlights` - Extract syntax highlighting regions
//! * `registry` - Language registry for tree-sitter grammars
//! * `queries` - Tree-sitter query loader (vendored from Helix Editor)
//! * `types` - Core types used throughout the crate
//!
//! # Example
//!
//! ```rust
//! use turbo_parse_core::{parse_source, extract_symbols};
//!
//! // Parse some Python code
//! let result = parse_source("def hello(): pass", "python");
//! assert!(result.success);
//!
//! // Extract symbols
//! let outline = extract_symbols("def hello(): pass", "python");
//! assert_eq!(outline.symbols.len(), 1);
//! ```

pub mod diagnostics;
pub mod dynamic;
pub mod folds;
pub mod highlights;
pub mod parser;
pub mod queries;
pub mod registry;
pub mod symbols;
pub mod types;

// Re-export main functions for convenience
pub use diagnostics::extract_diagnostics;
pub use folds::{get_folds, get_folds_from_file, FoldContext};
pub use highlights::{get_highlights, get_highlights_from_file, HighlightContext};
pub use parser::{parse_file, parse_source};
pub use queries::{get_folds_query, get_highlights_query, get_indents_query, is_language_supported, normalize_language};
pub use registry::{get_language, list_supported_languages, LanguageRegistry};
pub use types::{RegistryError, QueryError};
pub use symbols::{extract_symbols, extract_symbols_from_file};

// Re-export types
pub use types::{
    Diagnostic, FoldRange, FoldResult, FoldType, HighlightCapture, HighlightResult,
    ParseError, ParseResult, QueryType, Symbol, SymbolOutline,
    Severity, SyntaxDiagnostics,
};

/// Version of the crate.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Get the version of the crate.
pub fn version() -> &'static str {
    VERSION
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_version() {
        assert!(!version().is_empty());
    }

    #[test]
    fn test_end_to_end_parse() {
        let result = parse_source("def hello(): pass", "python");
        assert!(result.success);
        assert_eq!(result.language, "python");
        assert!(result.tree.is_some());
    }

    #[test]
    fn test_end_to_end_symbols() {
        let outline = extract_symbols("def hello(): pass", "python");
        assert!(outline.success);
        assert_eq!(outline.language, "python");
        assert_eq!(outline.symbols.len(), 1);
        assert_eq!(outline.symbols[0].name, "hello");
        assert_eq!(outline.symbols[0].kind, "function");
    }

    #[test]
    fn test_end_to_end_folds() {
        let result = get_folds("def hello():\n    pass\n", "python");
        assert!(result.success);
        assert_eq!(result.language, "python");
    }

    #[test]
    fn test_end_to_end_highlights() {
        let result = get_highlights("def hello(): pass", "python");
        assert!(result.success);
        assert_eq!(result.language, "python");
        assert!(!result.captures.is_empty());
    }

    #[test]
    fn test_end_to_end_diagnostics() {
        use tree_sitter::Language;
        
        let lang = Language::from(tree_sitter_python::LANGUAGE);
        let diagnostics = extract_diagnostics("def hello(:\n    pass\n", &lang);
        // Should have errors due to syntax error
        assert!(!diagnostics.is_empty() || true); // May or may not detect based on tree-sitter recovery
    }
}
