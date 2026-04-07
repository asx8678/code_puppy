//! Parser module — File and source code parsing with tree-sitter.
//!
//! Provides high-performance parsing with GIL release during CPU-intensive
//! tree-sitter operations. Returns structured parse results with timing info.

use std::path::Path;
use std::time::Instant;
use serde::{Deserialize, Serialize};
use tree_sitter::{Node, Parser, Tree};

use crate::registry::{get_language, RegistryError};
use crate::symbols::normalize_language;

/// A single parse error with location information.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParseError {
    /// Error message
    pub message: String,
    /// Line number where error occurred (1-indexed, 0 if unknown)
    pub line: usize,
    /// Column number where error occurred (0-indexed, 0 if unknown)
    pub column: usize,
    /// Byte offset in source where error occurred
    pub offset: usize,
}

impl ParseError {
    /// Create a new parse error.
    pub fn new(message: impl Into<String>, line: usize, column: usize, offset: usize) -> Self {
        Self {
            message: message.into(),
            line,
            column,
            offset,
        }
    }

    /// Create a simple error with just a message.
    pub fn with_message(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
            line: 0,
            column: 0,
            offset: 0,
        }
    }
}

/// Result of a parse operation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParseResult {
    /// The detected or specified language
    pub language: String,
    /// Serialized tree representation (None if parsing failed)
    pub tree: Option<serde_json::Value>,
    /// Time taken to parse in milliseconds
    pub parse_time_ms: f64,
    /// Whether the parse succeeded
    pub success: bool,
    /// Any parse errors encountered
    pub errors: Vec<ParseError>,
}

impl ParseResult {
    /// Create a new parse result.
    pub fn new(
        language: impl Into<String>,
        tree: Option<serde_json::Value>,
        parse_time_ms: f64,
        success: bool,
        errors: Vec<ParseError>,
    ) -> Self {
        Self {
            language: language.into(),
            tree,
            parse_time_ms,
            success,
            errors,
        }
    }

    /// Create an error result.
    pub fn error(language: impl Into<String>, error: ParseError) -> Self {
        Self {
            language: language.into(),
            tree: None,
            parse_time_ms: 0.0,
            success: false,
            errors: vec![error],
        }
    }
}

/// Detect language from file extension.
fn detect_language_from_path(path: &str) -> Option<String> {
    let ext = Path::new(path)
        .extension()
        .and_then(|e| e.to_str())?
        .to_lowercase();

    match ext.as_str() {
        "py" => Some("python".to_string()),
        "rs" => Some("rust".to_string()),
        "js" => Some("javascript".to_string()),
        "jsx" => Some("javascript".to_string()),
        "ts" => Some("typescript".to_string()),
        "tsx" => Some("tsx".to_string()),
        "ex" | "exs" => Some("elixir".to_string()),
        _ => None,
    }
}


/// Serialize a tree-sitter node to JSON.
fn serialize_node(node: Node, source: &str) -> serde_json::Value {
    let mut obj = serde_json::Map::new();
    
    obj.insert("type".to_string(), serde_json::Value::String(node.kind().to_string()));
    obj.insert("start".to_string(), serde_json::json!({
        "row": node.start_position().row,
        "column": node.start_position().column,
        "byte": node.start_byte(),
    }));
    obj.insert("end".to_string(), serde_json::json!({
        "row": node.end_position().row,
        "column": node.end_position().column,
        "byte": node.end_byte(),
    }));
    
    // Extract text if node is small enough (avoid huge strings)
    let text = node.utf8_text(source.as_bytes()).unwrap_or("");
    if text.len() <= 100 {
        obj.insert("text".to_string(), serde_json::Value::String(text.to_string()));
    }
    
    // Serialize children recursively
    let children: Vec<serde_json::Value> = (0..node.child_count())
        .filter_map(|i| node.child(i).map(|child| serialize_node(child, source)))
        .collect();
    
    if !children.is_empty() {
        obj.insert("children".to_string(), serde_json::Value::Array(children));
    }
    
    serde_json::Value::Object(obj)
}

/// Serialize a tree-sitter tree to JSON.
fn serialize_tree(tree: &Tree, source: &str) -> serde_json::Value {
    let root = tree.root_node();
    serde_json::json!({
        "root": serialize_node(root, source),
        "language": "tree-sitter",
    })
}

/// Extract parse errors from a tree (has_errors check).
fn extract_errors(tree: &Tree, source: &str) -> Vec<ParseError> {
    let mut errors = Vec::new();
    let root = tree.root_node();
    
    fn collect_errors(node: Node, source: &str, errors: &mut Vec<ParseError>) {
        if node.is_error() || node.is_missing() {
            let text = node.utf8_text(source.as_bytes()).unwrap_or("");
            let message = if node.is_missing() {
                format!("Missing: {}", node.kind())
            } else {
                format!("Syntax error: {}", text)
            };
            
            errors.push(ParseError::new(
                message,
                node.start_position().row + 1,  // 1-indexed line
                node.start_position().column,
                node.start_byte(),
            ));
        }
        
        for i in 0..node.child_count() {
            if let Some(child) = node.child(i) {
                collect_errors(child, source, errors);
            }
        }
    }
    
    collect_errors(root, source, &mut errors);
    errors
}

/// Internal parse implementation that doesn't need Python GIL.
/// This is the core parsing logic that runs with GIL released.
fn parse_source_internal(source: &str, language: &str) -> ParseResult {
    let lang_name = normalize_language(language);
    
    // Get the tree-sitter language
    let ts_language = match get_language(&lang_name) {
        Ok(lang) => lang,
        Err(RegistryError::UnsupportedLanguage(_)) => {
            return ParseResult::error(
                &lang_name,
                ParseError::with_message(format!("Unsupported language: '{}'", language))
            );
        }
        Err(e) => {
            return ParseResult::error(
                &lang_name,
                ParseError::with_message(format!("Language initialization error: {}", e))
            );
        }
    };
    
    let start = Instant::now();
    
    // Create and configure parser
    let mut parser = Parser::new();
    
    if let Err(e) = parser.set_language(ts_language) {
        return ParseResult::error(
            &lang_name,
            ParseError::with_message(format!("Failed to set language: {}", e))
        );
    }
    
    // Parse the source (this is the CPU-intensive operation)
    let tree = match parser.parse(source, None) {
        Some(t) => t,
        None => {
            return ParseResult::error(
                &lang_name,
                ParseError::with_message("Parser returned no tree")
            );
        }
    };
    
    let parse_time_ms = start.elapsed().as_secs_f64() * 1000.0;
    
    // Extract errors from the tree
    let errors = extract_errors(&tree, source);
    let has_errors = !errors.is_empty() || tree.root_node().has_error();
    
    // Serialize the tree
    let tree_json = serialize_tree(&tree, source);
    
    ParseResult::new(
        &lang_name,
        Some(tree_json),
        parse_time_ms,
        !has_errors,
        errors,
    )
}

/// Parse source code directly.
/// 
/// # Arguments
/// * `source` - The source code to parse
/// * `language` - The language identifier (e.g., "python", "rust")
///
/// # Returns
/// ParseResult with tree data and timing information.
pub fn parse_source(source: &str, language: &str) -> ParseResult {
    parse_source_internal(source, language)
}

/// Parse a file from disk.
///
/// # Arguments
/// * `path` - Path to the file
/// * `language` - Optional language override (detected from extension if not provided)
///
/// # Returns
/// ParseResult with tree data and timing information.
pub fn parse_file(path: &str, language: Option<&str>) -> ParseResult {
    // Detect language from path if not specified
    let lang = match language {
        Some(l) => l.to_string(),
        None => {
            match detect_language_from_path(path) {
                Some(l) => l,
                None => {
                    return ParseResult::error(
                        "unknown",
                        ParseError::with_message(format!(
                            "Could not detect language from path: '{}'. Please specify language explicitly.",
                            path
                        ))
                    );
                }
            }
        }
    };
    
    // Read file contents
    let source = match std::fs::read_to_string(path) {
        Ok(s) => s,
        Err(e) => {
            return ParseResult::error(
                &lang,
                ParseError::with_message(format!("Failed to read file '{}': {}", path, e))
            );
        }
    };
    
    parse_source_internal(&source, &lang)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_detect_language_from_path() {
        assert_eq!(detect_language_from_path("test.py"), Some("python".to_string()));
        assert_eq!(detect_language_from_path("test.rs"), Some("rust".to_string()));
        assert_eq!(detect_language_from_path("test.js"), Some("javascript".to_string()));
        assert_eq!(detect_language_from_path("test.jsx"), Some("javascript".to_string()));
        assert_eq!(detect_language_from_path("test.ts"), Some("typescript".to_string()));
        assert_eq!(detect_language_from_path("test.tsx"), Some("tsx".to_string()));
        assert_eq!(detect_language_from_path("test.ex"), Some("elixir".to_string()));
        assert_eq!(detect_language_from_path("test.exs"), Some("elixir".to_string()));
        assert_eq!(detect_language_from_path("test.unknown"), None);
        assert_eq!(detect_language_from_path("test"), None);
    }

    #[test]
    fn test_normalize_language() {
        assert_eq!(normalize_language("py"), "python");
        assert_eq!(normalize_language("python"), "python");
        assert_eq!(normalize_language("PY"), "python");
        assert_eq!(normalize_language("js"), "javascript");
        assert_eq!(normalize_language("ts"), "typescript");
        assert_eq!(normalize_language("ex"), "elixir");
        assert_eq!(normalize_language("rust"), "rust");
    }

    #[test]
    fn test_parse_source_python() {
        let source = r#"def hello():
    pass
"#;
        let result = parse_source(source, "python");
        
        assert_eq!(result.language, "python");
        assert!(result.success);
        assert!(result.tree.is_some());
        assert!(result.parse_time_ms >= 0.0);
    }

    #[test]
    fn test_parse_source_rust() {
        let source = r#"fn main() {
    println!("Hello, world!");
}
"#;
        let result = parse_source(source, "rust");
        
        assert_eq!(result.language, "rust");
        assert!(result.success);
        assert!(result.tree.is_some());
    }

    #[test]
    fn test_parse_source_javascript() {
        let source = r#"function hello() {
    return "world";
}
"#;
        let result = parse_source(source, "javascript");
        
        assert_eq!(result.language, "javascript");
        assert!(result.success);
        assert!(result.tree.is_some());
    }

    #[test]
    fn test_parse_source_unsupported() {
        let source = "some code";
        let result = parse_source(source, "unsupported_language");
        
        assert!(!result.success);
        assert!(result.tree.is_none());
        assert_eq!(result.errors.len(), 1);
    }

    #[test]
    fn test_parse_source_with_error() {
        // Python code with a syntax error
        let source = r#"def hello(
    pass  # Missing closing paren
"#;
        let result = parse_source(source, "python");
        
        // tree-sitter may still return a tree with recovery
        assert!(result.tree.is_some());
        // But should report errors
        assert!(!result.errors.is_empty() || !result.success);
    }

    #[test]
    fn test_parse_error_creation() {
        let err = ParseError::new("test error", 10, 5, 100);
        assert_eq!(err.message, "test error");
        assert_eq!(err.line, 10);
        assert_eq!(err.column, 5);
        assert_eq!(err.offset, 100);
    }

    #[test]
    fn test_parse_result_error_factory() {
        let err = ParseError::with_message("test");
        let result = ParseResult::error("python", err);
        
        assert_eq!(result.language, "python");
        assert!(!result.success);
        assert!(result.tree.is_none());
        assert_eq!(result.errors.len(), 1);
    }
}
