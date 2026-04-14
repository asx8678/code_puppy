//! Code folding query runner using tree-sitter.
//!
//! Provides extraction of foldable regions (functions, classes, blocks)
//! from source code in Python, Rust, JavaScript, TypeScript, TSX, and Elixir.

use std::time::Instant;
use streaming_iterator::StreamingIterator;
use tree_sitter::{Language, Parser, Query, QueryCursor};

use crate::queries::{get_folds_query, normalize_language};
use crate::registry::get_language;
use crate::types::{FoldRange, FoldResult, FoldType, QueryError, RegistryError};

impl FoldType {
    /// Create a FoldType from a tree-sitter node kind.
    fn from_node_kind(kind: &str, language: &str) -> Self {
        match (language, kind) {
            // Python
            ("python", "function_definition") => FoldType::Function,
            ("python", "class_definition") => FoldType::Class,
            ("python", "if_statement" | "match_statement") => FoldType::Conditional,
            ("python", "for_statement" | "while_statement") => FoldType::Loop,
            ("python", "with_statement" | "try_statement" | "import_from_statement") => FoldType::Block,

            // Rust
            ("rust", "function_item") => FoldType::Function,
            ("rust", "struct_item" | "enum_item" | "trait_item") => FoldType::Class,
            ("rust", "impl_item" | "mod_item") => FoldType::Block,
            ("rust", "if_expression" | "match_expression") => FoldType::Conditional,
            ("rust", "for_expression" | "while_expression" | "loop_expression") => FoldType::Loop,
            ("rust", "use_declaration") => FoldType::Import,

            // JavaScript/TypeScript/TSX
            ("javascript" | "typescript" | "tsx", "function_declaration" | "function_expression" | "arrow_function") => FoldType::Function,
            ("javascript" | "typescript" | "tsx", "class_declaration" | "class_expression") => FoldType::Class,
            ("javascript" | "typescript" | "tsx", "method_definition") => FoldType::Function,
            ("javascript" | "typescript" | "tsx", "if_statement" | "switch_statement") => FoldType::Conditional,
            ("javascript" | "typescript" | "tsx", "for_statement" | "while_statement" | "do_statement") => FoldType::Loop,
            ("javascript" | "typescript" | "tsx", "try_statement") => FoldType::Block,
            ("javascript" | "typescript" | "tsx", "object" | "array") => FoldType::Generic,
            ("javascript" | "typescript" | "tsx", "import_statement" | "export_statement") => FoldType::Import,
            ("typescript" | "tsx", "interface_declaration" | "enum_declaration" | "type_alias_declaration") => FoldType::Class,
            ("tsx", "jsx_element" | "jsx_self_closing_element" | "jsx_fragment") => FoldType::Generic,

            // Elixir
            ("elixir", _) => {
                // Elixir uses call nodes with specific targets for most constructs
                if kind.contains("call") {
                    FoldType::Function
                } else if kind.contains("block") {
                    FoldType::Block
                } else {
                    FoldType::Generic
                }
            }

            // Default
            _ => FoldType::Generic,
        }
    }
}

/// Context for managing fold query state.
///
/// This struct allows reusing parsed queries for better performance
/// when processing multiple files with the same language.
pub struct FoldContext {
    /// The tree-sitter language
    language: Language,
    /// The normalized language name
    language_name: String,
    /// The compiled query (optional, loaded on demand)
    query: Option<Query>,
}

impl FoldContext {
    /// Create a new fold context for a language.
    ///
    /// # Arguments
    /// * `language` - The language identifier (e.g., "python", "rust")
    ///
    /// # Returns
    /// A `FoldContext` on success, or a `FoldResult` error on failure.
    pub fn new(language: &str) -> Result<Self, FoldResult> {
        let normalized = normalize_language(language);

        let ts_language = match get_language(&normalized) {
            Ok(lang) => lang,
            Err(RegistryError::UnsupportedLanguage(_)) => {
                return Err(FoldResult::error(
                    &normalized,
                    format!("Unsupported language: '{}'", language),
                ));
            }
            Err(e) => {
                return Err(FoldResult::error(
                    &normalized,
                    format!("Language initialization error: {}", e),
                ));
            }
        };

        Ok(Self {
            language: ts_language.clone(),
            language_name: normalized,
            query: None,
        })
    }

    /// Load the fold query for this context.
    fn load_query(&mut self) -> Result<&Query, String> {
        if self.query.is_none() {
            let query_str = match get_folds_query(&self.language_name) {
                Ok(q) => q,
                Err(QueryError::UnsupportedLanguage(_)) => {
                    return Err(format!("Folds not supported for: {}", self.language_name));
                }
                Err(QueryError::QueryTypeNotAvailable { language, query_type }) => {
                    return Err(format!(
                        "Query type '{}' not available for '{}'",
                        query_type, language
                    ));
                }
            };

            let query = Query::new(&self.language, query_str)
                .map_err(|e| format!("Failed to compile fold query: {:?}", e))?;

            self.query = Some(query);
        }

        Ok(self.query.as_ref().unwrap())
    }

    /// Get folds for source code using this context.
    ///
    /// This method reuses the parsed query from the context,
    /// making it more efficient for repeated operations.
    pub fn get_folds(&mut self, source: &str) -> FoldResult {
        let start = Instant::now();

        // Clone language info before mutable borrow
        let lang = self.language.clone();
        let lang_name = self.language_name.clone();

        // Load the query
        let query = match self.load_query() {
            Ok(q) => q,
            Err(e) => return FoldResult::error(&lang_name, e),
        };

        // Parse the source
        let mut parser = Parser::new();
        if let Err(e) = parser.set_language(&lang) {
            return FoldResult::error(
                &lang_name,
                format!("Failed to set language: {}", e),
            );
        }

        let tree = match parser.parse(source, None) {
            Some(t) => t,
            None => {
                return FoldResult::error(
                    &lang_name,
                    "Parser returned no tree",
                );
            }
        };

        // Execute the fold query
        let folds = execute_fold_query(query, &tree, source, &lang_name);
        let extraction_time_ms = start.elapsed().as_secs_f64() * 1000.0;

        FoldResult::new(&lang_name, folds, extraction_time_ms)
    }
}

/// Execute a fold query on a parsed tree.
fn execute_fold_query(
    query: &Query,
    tree: &tree_sitter::Tree,
    source: &str,
    lang_name: &str,
) -> Vec<FoldRange> {
    let mut folds: Vec<FoldRange> = Vec::new();

    // Execute the query
    let mut cursor = QueryCursor::new();
    let mut matches = cursor.matches(query, tree.root_node(), source.as_bytes());

    // Find the @fold capture index
    let fold_capture_idx = query.capture_names().iter().position(|name| *name == "fold");

    while let Some(m) = matches.next() {
        for capture in m.captures {
            // Only process @fold captures
            if let Some(fold_idx) = fold_capture_idx {
                if capture.index as usize != fold_idx {
                    continue;
                }
            }

            let node = capture.node;
            let start_pos = node.start_position();
            let end_pos = node.end_position();

            let start_line = start_pos.row + 1; // 1-indexed
            let end_line = end_pos.row + 1;

            // Determine fold type from node kind
            let node_kind = node.kind();
            let fold_type = FoldType::from_node_kind(node_kind, lang_name);

            // Check for duplicates (same start/end lines)
            let exists = folds.iter().any(|f| {
                f.start_line == start_line && f.end_line == end_line
            });

            if !exists && end_line > start_line {
                folds.push(
                    FoldRange::new(start_line, end_line, fold_type)
                        .with_node_kind(node_kind),
                );
            }
        }
    }

    // Sort by start line, then by end line (descending) to get outer folds first
    folds.sort_by(|a, b| {
        a.start_line
            .cmp(&b.start_line)
            .then(b.end_line.cmp(&a.end_line))
    });

    folds
}

/// Get folds for source code.
///
/// This is the main entry point for getting fold ranges from source code.
/// It handles parsing, query execution, and error handling.
///
/// # Arguments
/// * `source` - The source code to analyze
/// * `language` - The language identifier (e.g., "python", "rust")
///
/// # Returns
/// A `FoldResult` containing all fold ranges found in the source.
pub fn get_folds(source: &str, language: &str) -> FoldResult {
    let mut context = match FoldContext::new(language) {
        Ok(ctx) => ctx,
        Err(result) => return result,
    };

    context.get_folds(source)
}

/// Get folds from a file.
///
/// # Arguments
/// * `path` - Path to the file
/// * `language` - Optional language override (detected from extension if not provided)
///
/// # Returns
/// A `FoldResult` containing all fold ranges found in the file.
pub fn get_folds_from_file(path: &str, language: Option<&str>) -> FoldResult {
    use std::path::Path;

    // Detect language from path if not specified
    let lang = match language {
        Some(l) => l.to_string(),
        None => {
            let ext = Path::new(path)
                .extension()
                .and_then(|e| e.to_str())
                .unwrap_or("")
                .to_lowercase();

            match ext.as_str() {
                "py" => "python".to_string(),
                "rs" => "rust".to_string(),
                "js" => "javascript".to_string(),
                "ts" => "typescript".to_string(),
                "tsx" => "tsx".to_string(),
                "ex" | "exs" => "elixir".to_string(),
                _ => {
                    return FoldResult::error(
                        "unknown",
                        format!("Cannot detect language from path: {}", path),
                    );
                }
            }
        }
    };

    // Read file
    let source = match std::fs::read_to_string(path) {
        Ok(s) => s,
        Err(e) => {
            return FoldResult::error(
                &lang,
                format!("Failed to read file '{}': {}", path, e),
            );
        }
    };

    get_folds(&source, &lang)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_fold_type_display() {
        assert_eq!(format!("{}", FoldType::Function), "function");
        assert_eq!(format!("{}", FoldType::Class), "class");
        assert_eq!(format!("{}", FoldType::Conditional), "conditional");
        assert_eq!(format!("{}", FoldType::Loop), "loop");
        assert_eq!(format!("{}", FoldType::Block), "block");
        assert_eq!(format!("{}", FoldType::Import), "import");
        assert_eq!(format!("{}", FoldType::Generic), "generic");
    }

    #[test]
    fn test_fold_range_new() {
        let fold = FoldRange::new(1, 10, FoldType::Function);
        assert_eq!(fold.start_line, 1);
        assert_eq!(fold.end_line, 10);
        assert_eq!(fold.fold_type, FoldType::Function);
        assert!(fold.node_kind.is_none());
    }

    #[test]
    fn test_fold_range_with_node_kind() {
        let fold = FoldRange::new(1, 10, FoldType::Class).with_node_kind("class_definition");
        assert_eq!(fold.node_kind, Some("class_definition".to_string()));
    }

    #[test]
    fn test_fold_result_new() {
        let folds = vec![
            FoldRange::new(1, 5, FoldType::Function),
            FoldRange::new(7, 15, FoldType::Class),
        ];
        let result = FoldResult::new("python", folds, 0.5);

        assert_eq!(result.language, "python");
        assert_eq!(result.folds.len(), 2);
        assert!(result.success);
        assert!(result.errors.is_empty());
        assert_eq!(result.extraction_time_ms, 0.5);
    }

    #[test]
    fn test_fold_result_error() {
        let result = FoldResult::error("python", "test error");

        assert_eq!(result.language, "python");
        assert!(!result.success);
        assert_eq!(result.errors.len(), 1);
        assert_eq!(result.errors[0], "test error");
        assert!(result.folds.is_empty());
    }

    #[test]
    fn test_fold_result_filtering() {
        let folds = vec![
            FoldRange::new(1, 5, FoldType::Function),
            FoldRange::new(7, 15, FoldType::Class),
            FoldRange::new(17, 20, FoldType::Function),
        ];
        let result = FoldResult::new("python", folds, 0.5);

        let functions = result.folds_of_type(&FoldType::Function);
        assert_eq!(functions.len(), 2);

        let classes = result.folds_of_type(&FoldType::Class);
        assert_eq!(classes.len(), 1);
        assert_eq!(classes[0].start_line, 7);
    }

    #[test]
    fn test_get_folds_python_function() {
        let source = r#"def hello():
    pass
"#;
        let result = get_folds(source, "python");

        assert!(result.success);
        assert_eq!(result.language, "python");
        assert!(result.folds.iter().any(|f| {
            f.fold_type == FoldType::Function && f.start_line == 1
        }));
    }

    #[test]
    fn test_get_folds_python_class() {
        let source = r#"class MyClass:
    def method(self):
        pass
"#;
        let result = get_folds(source, "python");

        assert!(result.success);
        assert!(result.folds.iter().any(|f| {
            f.fold_type == FoldType::Class && f.start_line == 1
        }));
        assert!(result.folds.iter().any(|f| {
            f.fold_type == FoldType::Function && f.start_line == 2
        }));
    }

    #[test]
    fn test_get_folds_rust_function() {
        let source = r#"fn main() {
    println!("Hello");
}
"#;
        let result = get_folds(source, "rust");

        assert!(result.success);
        assert_eq!(result.language, "rust");
        assert!(result.folds.iter().any(|f| {
            f.fold_type == FoldType::Function && f.start_line == 1
        }));
    }

    #[test]
    fn test_get_folds_rust_struct_impl() {
        let source = r#"struct Point {
    x: i32,
    y: i32,
}

impl Point {
    fn new(x: i32, y: i32) -> Self {
        Point { x, y }
    }
}
"#;
        let result = get_folds(source, "rust");

        assert!(result.success);
        assert!(result.folds.iter().any(|f| f.fold_type == FoldType::Class)); // struct
        assert!(result.folds.iter().any(|f| f.fold_type == FoldType::Block)); // impl
        assert!(result.folds.iter().any(|f| f.fold_type == FoldType::Function));
    }

    #[test]
    fn test_get_folds_javascript() {
        let source = r#"function greet() {
    return "Hello";
}

class MyClass {
    doSomething() {}
}
"#;
        let result = get_folds(source, "javascript");

        assert!(result.success);
        assert!(result.folds.iter().any(|f| {
            f.fold_type == FoldType::Function && f.start_line == 1
        }));
        assert!(result.folds.iter().any(|f| {
            f.fold_type == FoldType::Class && f.start_line == 5
        }));
    }

    #[test]
    fn test_get_folds_typescript() {
        let source = r#"interface User {
    name: string;
}

function getUser(): User {
    return { name: "test" };
}
"#;
        let result = get_folds(source, "typescript");

        assert!(result.success);
        assert!(result.folds.iter().any(|f| f.fold_type == FoldType::Function));
        assert!(result.folds.iter().any(|f| f.fold_type == FoldType::Class)); // interface
    }

    #[test]
    fn test_get_folds_unsupported_language() {
        let source = "some code";
        let result = get_folds(source, "unsupported");

        assert!(!result.success);
        assert!(!result.errors.is_empty());
    }

    #[test]
    fn test_get_folds_empty_file() {
        let source = "";
        let result = get_folds(source, "python");

        assert!(result.success);
        assert!(result.folds.is_empty());
    }

    #[test]
    fn test_fold_context_new() {
        let context = FoldContext::new("python");
        assert!(context.is_ok());

        let context = context.unwrap();
        assert_eq!(context.language_name, "python");
    }

    #[test]
    fn test_fold_context_unsupported() {
        let context = FoldContext::new("unsupported");
        assert!(context.is_err());
    }

    #[test]
    fn test_fold_context_reuse() {
        let mut context = FoldContext::new("python").unwrap();

        // First call
        let source1 = "def a(): pass\n";
        let result1 = context.get_folds(source1);
        assert!(result1.success);

        // Second call reuses the query
        let source2 = "def b(): pass\n";
        let result2 = context.get_folds(source2);
        assert!(result2.success);
    }

    #[test]
    fn test_fold_context_elixir() {
        let source = r#"defmodule MyModule do
    def hello do
        :world
    end
end
"#;
        let result = get_folds(source, "elixir");

        assert!(result.success);
        assert_eq!(result.language, "elixir");
        assert!(!result.folds.is_empty());
    }

    #[test]
    fn test_get_folds_from_file_not_found() {
        let result = get_folds_from_file("/nonexistent/file.py", None);

        assert!(!result.success);
        assert!(!result.errors.is_empty());
        assert!(result.errors[0].contains("Failed to read file"));
    }

    #[test]
    fn test_get_folds_from_file_unknown_extension() {
        let result = get_folds_from_file("file.unknown", None);

        assert!(!result.success);
        assert!(!result.errors.is_empty());
        assert!(result.errors[0].contains("Cannot detect language"));
    }
}
