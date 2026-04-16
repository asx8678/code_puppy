//! Syntax highlighting query runner using tree-sitter queries.
//!
//! Provides extraction of syntax highlighting regions from source code
//! using the vendored Helix Editor queries/highlights.scm files.
//!
//! # Supported Languages
//! - Python
//! - Rust
//! - JavaScript
//! - TypeScript
//! - TSX
//! - Elixir
//!
//! # Capture Names
//! Capture names follow Helix Editor conventions:
//! - `keyword` - Keywords (def, class, if, etc.)
//! - `keyword.control` - Control flow (if, else, return, etc.)
//! - `string` - String literals
//! - `comment` - Comments
//! - `function` - Function definitions and calls
//! - `function.method` - Method calls
//! - `type` - Type names
//! - `variable` - Variables
//! - `constant` - Constants
//! - `operator` - Operators
//! - `punctuation` - Punctuation
//! - And more (see Helix documentation for full list)

use std::time::Instant;
use serde::{Deserialize, Serialize};
use streaming_iterator::StreamingIterator;
use tree_sitter::{Language, Parser, Query, QueryCursor};

use crate::queries::get_highlights_query;
use crate::registry::{get_language, normalize_language};

/// A single highlight capture region.
///
/// Represents a syntax-highlightable region of source code with
/// its byte position and capture name (e.g., "keyword", "string").
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[pyo3::pyclass(frozen)]
pub struct HighlightCapture {
    /// Start byte position in the source (0-indexed, inclusive)
    pub start_byte: usize,
    /// End byte position in the source (0-indexed, exclusive)
    pub end_byte: usize,
    /// Capture name following Helix conventions (e.g., "keyword", "string")
    pub capture_name: String,
}

impl HighlightCapture {
    /// Create a new highlight capture.
    pub fn new(
        start_byte: usize,
        end_byte: usize,
        capture_name: impl Into<String>,
    ) -> Self {
        Self {
            start_byte,
            end_byte,
            capture_name: capture_name.into(),
        }
    }

    /// Get the length of the capture in bytes.
    pub fn len(&self) -> usize {
        self.end_byte.saturating_sub(self.start_byte)
    }

    /// Check if the capture is empty.
    pub fn is_empty(&self) -> bool {
        self.start_byte == self.end_byte
    }

    /// Get the captured text from the source.
    pub fn text<'a>(&self, source: &'a str) -> Option<&'a str> {
        source.get(self.start_byte..self.end_byte)
    }

    /// Check if this capture overlaps with another.
    pub fn overlaps(&self, other: &HighlightCapture) -> bool {
        self.start_byte < other.end_byte && other.start_byte < self.end_byte
    }

    /// Check if this capture contains a byte position.
    pub fn contains(&self, byte: usize) -> bool {
        self.start_byte <= byte && byte < self.end_byte
    }
}

/// Result of a highlight extraction operation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HighlightResult {
    /// The programming language
    pub language: String,
    /// All highlight captures found, ordered by position
    pub captures: Vec<HighlightCapture>,
    /// Time taken to extract highlights in milliseconds
    pub extraction_time_ms: f64,
    /// Whether the extraction succeeded
    pub success: bool,
    /// Any errors encountered during extraction
    pub errors: Vec<String>,
}

impl HighlightResult {
    /// Create a new successful highlight result.
    pub fn new(
        language: impl Into<String>,
        captures: Vec<HighlightCapture>,
        extraction_time_ms: f64,
    ) -> Self {
        Self {
            language: language.into(),
            captures,
            extraction_time_ms,
            success: true,
            errors: Vec::new(),
        }
    }

    /// Create an error result.
    pub fn error(language: impl Into<String>, error: impl Into<String>) -> Self {
        Self {
            language: language.into(),
            captures: Vec::new(),
            extraction_time_ms: 0.0,
            success: false,
            errors: vec![error.into()],
        }
    }

    /// Get captures of a specific type.
    pub fn captures_of_type(&self, capture_name: &str) -> Vec<&HighlightCapture> {
        self.captures
            .iter()
            .filter(|c| c.capture_name == capture_name)
            .collect()
    }

    /// Get the number of captures.
    pub fn len(&self) -> usize {
        self.captures.len()
    }

    /// Check if there are any captures.
    pub fn is_empty(&self) -> bool {
        self.captures.is_empty()
    }
}

/// Context for efficient highlight query execution.
///
/// This struct manages the parsed query and can be reused across multiple
/// highlight extractions for the same language, improving performance
/// when highlighting many files.
#[derive(Debug)]
pub struct HighlightContext {
    language: Language,
    query: Query,
    language_name: String,
}

impl HighlightContext {
    /// Create a new highlight context for a language.
    ///
    /// # Arguments
    /// * `language_name` - The language identifier (e.g., "python", "rust")
    ///
    /// # Returns
    /// Ok(HighlightContext) on success, or Err with error message
    ///
    /// # Example
    /// ```rust
    /// use turbo_parse::highlights::HighlightContext;
    ///
    /// let ctx = HighlightContext::new("python").unwrap();
    /// let result = ctx.get_highlights("def hello(): pass");
    /// ```
    pub fn new(language_name: &str) -> Result<Self, String> {
        let lang_name = normalize_language(language_name);

        // Get the tree-sitter language (returns &'static Language)
        let ts_language = get_language(&lang_name).map_err(|e| e.to_string())?;

        // Get the highlights query
        let query_str = get_highlights_query(&lang_name)
            .map_err(|e| format!("Failed to load highlights query: {}", e))?;

        // Parse the query (Query::new expects &Language)
        let query = Query::new(&ts_language, query_str)
            .map_err(|e| format!("Query error: {:?}", e))?;

        // Store the Language
        Ok(Self {
            language: ts_language,
            query,
            language_name: lang_name,
        })
    }

    /// Get highlights for source code using the cached query.
    ///
    /// This method reuses the pre-parsed query for better performance
    /// when highlighting multiple files of the same language.
    ///
    /// # Arguments
    /// * `source` - The source code to highlight
    ///
    /// # Returns
    /// A HighlightResult containing all captures
    pub fn get_highlights(&self, source: &str) -> HighlightResult {
        let start = Instant::now();

        // Parse the source
        let mut parser = Parser::new();
        if let Err(e) = parser.set_language(&self.language) {
            return HighlightResult::error(
                &self.language_name,
                format!("Failed to set language: {}", e),
            );
        }

        let tree = match parser.parse(source, None) {
            Some(t) => t,
            None => {
                return HighlightResult::error(
                    &self.language_name,
                    "Parser returned no tree",
                );
            }
        };

        // Execute the highlights query
        let captures = self.execute_query(&tree, source);
        let extraction_time_ms = start.elapsed().as_secs_f64() * 1000.0;

        HighlightResult::new(&self.language_name, captures, extraction_time_ms)
    }

    /// Execute the highlights query and collect captures.
    fn execute_query(&self, tree: &tree_sitter::Tree, source: &str) -> Vec<HighlightCapture> {
        let mut captures: Vec<HighlightCapture> = Vec::new();
        let capture_names = self.query.capture_names();

        let mut cursor = QueryCursor::new();
        let mut matches = cursor.matches(&self.query, tree.root_node(), source.as_bytes());

        while let Some(m) = matches.next() {
            for capture in m.captures {
                let node = capture.node;
                let capture_name = &capture_names[capture.index as usize];

                captures.push(HighlightCapture::new(
                    node.start_byte(),
                    node.end_byte(),
                    capture_name.clone(),
                ));
            }
        }

        // Sort by position for ordered output
        captures.sort_by(|a, b| {
            a.start_byte
                .cmp(&b.start_byte)
                .then(a.end_byte.cmp(&b.end_byte))
        });

        // Merge overlapping captures (later captures take precedence for nested structures)
        // This handles cases like "keyword.control.conditional" inside "keyword.control"
        captures = merge_overlapping_captures(captures);

        captures
    }

    /// Get the language name.
    pub fn language_name(&self) -> &str {
        &self.language_name
    }

    /// Get the query capture names.
    pub fn capture_names(&self) -> &[&str] {
        self.query.capture_names()
    }
}

/// Merge overlapping captures, preferring more specific capture names.
///
/// When captures overlap (e.g., "keyword.control.conditional" overlapping with
/// "keyword.control"), we keep the more specific (longer) capture name.
/// Captures are assumed to be sorted by start_byte.
fn merge_overlapping_captures(captures: Vec<HighlightCapture>) -> Vec<HighlightCapture> {
    if captures.is_empty() {
        return captures;
    }

    let mut result: Vec<HighlightCapture> = Vec::new();

    for capture in captures {
        // Check if this capture overlaps with the last one we kept
        if let Some(last) = result.last_mut() {
            if last.overlaps(&capture) {
                // Same range: keep the more specific one
                if last.start_byte == capture.start_byte && last.end_byte == capture.end_byte {
                    // Both cover exactly the same range - keep more specific (longer) name
                    if capture.capture_name.len() > last.capture_name.len()
                        && capture.capture_name.starts_with(&last.capture_name)
                    {
                        *last = capture;
                    }
                    // Otherwise keep the existing one
                    continue;
                }
                // Different ranges that overlap - skip the later one
                // (the earlier one takes precedence)
                continue;
            }
        }
        result.push(capture);
    }

    result
}

/// Get syntax highlights for source code.
///
/// # Arguments
/// * `source` - The source code to analyze
/// * `language` - The language identifier (e.g., "python", "rust", "javascript")
///
/// # Returns
/// A HighlightResult containing all captures with their byte positions and capture names.
/// Captures are ordered by position (start_byte ascending).
///
/// # Example
/// ```rust
/// use turbo_parse::highlights::get_highlights;
///
/// let source = r#"def hello():
///     pass
/// ""#;
/// let result = get_highlights(source, "python");
/// assert!(result.success);
/// assert!(!result.captures.is_empty());
///
/// // Check for keyword capture
/// let has_keyword = result.captures.iter().any(|c| c.capture_name == "keyword");
/// assert!(has_keyword);
/// ```
pub fn get_highlights(source: &str, language: &str) -> HighlightResult {
    match HighlightContext::new(language) {
        Ok(ctx) => ctx.get_highlights(source),
        Err(e) => HighlightResult::error(language, e),
    }
}

/// Get highlights for a file.
///
/// # Arguments
/// * `path` - Path to the file
/// * `language` - Optional language override (detected from extension if not provided)
///
/// # Returns
/// A HighlightResult containing all captures, or error if file cannot be read.
pub fn get_highlights_from_file(path: &str, language: Option<&str>) -> HighlightResult {
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
                "jsx" => "javascript".to_string(),
                "ts" => "typescript".to_string(),
                "tsx" => "tsx".to_string(),
                "ex" | "exs" => "elixir".to_string(),
                _ => {
                    return HighlightResult::error(
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
            return HighlightResult::error(
                &lang,
                format!("Failed to read file '{}': {}", path, e),
            );
        }
    };

    get_highlights(&source, &lang)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_highlight_capture_new() {
        let cap = HighlightCapture::new(0, 5, "keyword");
        assert_eq!(cap.start_byte, 0);
        assert_eq!(cap.end_byte, 5);
        assert_eq!(cap.capture_name, "keyword");
        assert_eq!(cap.len(), 5);
        assert!(!cap.is_empty());
    }

    #[test]
    fn test_highlight_capture_empty() {
        let cap = HighlightCapture::new(10, 10, "comment");
        assert!(cap.is_empty());
        assert_eq!(cap.len(), 0);
    }

    #[test]
    fn test_highlight_capture_text() {
        let source = "def hello(): pass";
        let cap = HighlightCapture::new(0, 3, "keyword");
        assert_eq!(cap.text(source), Some("def"));

        let cap2 = HighlightCapture::new(100, 105, "invalid");
        assert_eq!(cap2.text(source), None);
    }

    #[test]
    fn test_highlight_capture_overlaps() {
        let cap1 = HighlightCapture::new(0, 5, "keyword");
        let cap2 = HighlightCapture::new(3, 8, "variable");
        let cap3 = HighlightCapture::new(10, 15, "string");

        assert!(cap1.overlaps(&cap2));
        assert!(cap2.overlaps(&cap1));
        assert!(!cap1.overlaps(&cap3));
        assert!(!cap3.overlaps(&cap1));
    }

    #[test]
    fn test_highlight_capture_contains() {
        let cap = HighlightCapture::new(10, 20, "function");
        assert!(cap.contains(10));
        assert!(cap.contains(15));
        assert!(cap.contains(19));
        assert!(!cap.contains(20)); // end_byte is exclusive
        assert!(!cap.contains(5));
        assert!(!cap.contains(25));
    }

    #[test]
    fn test_highlight_result_new() {
        let caps = vec![
            HighlightCapture::new(0, 3, "keyword"),
            HighlightCapture::new(4, 10, "function"),
        ];
        let result = HighlightResult::new("python", caps, 1.5);

        assert_eq!(result.language, "python");
        assert_eq!(result.len(), 2);
        assert!(result.success);
        assert!(result.errors.is_empty());
        assert_eq!(result.extraction_time_ms, 1.5);
    }

    #[test]
    fn test_highlight_result_error() {
        let result = HighlightResult::error("python", "test error");

        assert_eq!(result.language, "python");
        assert!(!result.success);
        assert_eq!(result.errors.len(), 1);
        assert_eq!(result.errors[0], "test error");
        assert!(result.captures.is_empty());
    }

    #[test]
    fn test_highlight_result_captures_of_type() {
        let caps = vec![
            HighlightCapture::new(0, 3, "keyword"),
            HighlightCapture::new(4, 8, "string"),
            HighlightCapture::new(12, 18, "keyword"),
        ];
        let result = HighlightResult::new("python", caps, 1.0);

        let keywords = result.captures_of_type("keyword");
        assert_eq!(keywords.len(), 2);

        let strings = result.captures_of_type("string");
        assert_eq!(strings.len(), 1);

        let missing = result.captures_of_type("comment");
        assert!(missing.is_empty());
    }

    #[test]
    fn test_merge_overlapping_captures() {
        // Test same-range replacement: more specific capture replaces less specific
        let caps = vec![
            HighlightCapture::new(0, 10, "keyword"),
            HighlightCapture::new(0, 10, "keyword.control"), // More specific, same range - should replace
        ];

        let merged = merge_overlapping_captures(caps);

        // Should have: keyword.control (replaced keyword)
        assert_eq!(merged.len(), 1);
        assert_eq!(merged[0].capture_name, "keyword.control");

        // Test non-overlapping captures are preserved
        let caps2 = vec![
            HighlightCapture::new(0, 5, "keyword"),
            HighlightCapture::new(10, 15, "variable"),
        ];

        let merged2 = merge_overlapping_captures(caps2);
        assert_eq!(merged2.len(), 2);
        assert_eq!(merged2[0].capture_name, "keyword");
        assert_eq!(merged2[1].capture_name, "variable");
    }

    // ============================================================================
    // Python Highlight Tests
    // ============================================================================

    #[test]
    fn test_get_highlights_python_keywords() {
        let source = "def hello():\n    pass";
        let result = get_highlights(source, "python");

        assert!(result.success);
        assert_eq!(result.language, "python");

        // Check for 'def' and 'pass' keywords
        let keyword_captures: Vec<_> = result
            .captures
            .iter()
            .filter(|c| c.capture_name == "keyword" || c.capture_name == "keyword.function")
            .collect();
        assert!(
            !keyword_captures.is_empty(),
            "Should find keyword captures for 'def'"
        );
    }

    #[test]
    fn test_get_highlights_python_function() {
        let source = "def hello():\n    pass";
        let result = get_highlights(source, "python");

        assert!(result.success);

        // Look for function name
        let has_function = result.captures.iter().any(|c| {
            c.capture_name == "function"
                && c.text(source).map_or(false, |t| t.contains("hello"))
        });
        assert!(has_function, "Should capture function name 'hello'");
    }

    #[test]
    fn test_get_highlights_python_string() {
        let source = r#"message = "hello world""#;
        let result = get_highlights(source, "python");

        assert!(result.success);

        // Look for string capture
        let has_string = result.captures.iter().any(|c| {
            c.capture_name == "string" && c.text(source).map_or(false, |t| t.contains("hello"))
        });
        assert!(has_string, "Should capture string literal");
    }

    #[test]
    fn test_get_highlights_python_comment() {
        let source = "# This is a comment\nprint(1)";
        let result = get_highlights(source, "python");

        assert!(result.success);

        // Look for comment capture
        let has_comment = result.captures.iter().any(|c| {
            c.capture_name == "comment" && c.text(source).map_or(false, |t| t.contains("#"))
        });
        assert!(has_comment, "Should capture comment");
    }

    #[test]
    fn test_get_highlights_python_class() {
        let source = "class MyClass:\n    pass";
        let result = get_highlights(source, "python");

        assert!(result.success);

        // Should have class keyword
        let has_class_keyword = result.captures.iter().any(|c| {
            c.text(source).map_or(false, |t| t == "class")
                && (c.capture_name == "keyword" || c.capture_name.contains("class"))
        });
        assert!(has_class_keyword, "Should capture 'class' keyword");

        // Should have type name
        let has_type = result.captures.iter().any(|c| {
            c.capture_name == "type" && c.text(source).map_or(false, |t| t == "MyClass")
        });
        assert!(has_type, "Should capture class name 'MyClass' as type");
    }

    // ============================================================================
    // Rust Highlight Tests
    // ============================================================================

    #[test]
    fn test_get_highlights_rust_keywords() {
        let source = "fn main() {\n    let x = 42;\n}";
        let result = get_highlights(source, "rust");

        assert!(result.success);
        assert_eq!(result.language, "rust");

        // Check for function keyword (fn is @keyword.function in Rust)
        let has_fn = result.captures.iter().any(|c| {
            c.text(source).map_or(false, |t| t == "fn")
                && (c.capture_name == "keyword" || c.capture_name.contains("function"))
        });
        assert!(has_fn, "Should capture 'fn' keyword");

        // Check for let keyword (let is @keyword.storage in Rust)
        let has_let = result.captures.iter().any(|c| {
            c.text(source).map_or(false, |t| t == "let")
                && (c.capture_name == "keyword" || c.capture_name.contains("keyword"))
        });
        assert!(has_let, "Should capture 'let' keyword");
    }
    #[test]
    fn test_get_highlights_rust_function() {
        let source = "fn my_function() -> i32 { 42 }";
        let result = get_highlights(source, "rust");

        assert!(result.success);

        // Look for function name
        let has_function = result.captures.iter().any(|c| {
            c.capture_name == "function"
                && c.text(source).map_or(false, |t| t.contains("my_function"))
        });
        assert!(has_function, "Should capture function name 'my_function'");
    }

    #[test]
    fn test_get_highlights_rust_macro() {
        let source = "println!(\"Hello, world!\")";
        let result = get_highlights(source, "rust");

        assert!(result.success);

        // Look for macro or function call
        let has_println = result.captures.iter().any(|c| {
            c.text(source).map_or(false, |t| t.contains("println"))
        });
        assert!(has_println, "Should capture 'println'");
    }

    #[test]
    fn test_get_highlights_rust_types() {
        let source = "let x: i32 = 42;";
        let result = get_highlights(source, "rust");

        assert!(result.success);

        // Look for primitive type (i32 is @type.builtin in Rust)
        let has_type = result.captures.iter().any(|c| {
            c.capture_name.contains("type")
                && c.text(source).map_or(false, |t| t.contains("i32"))
        });
        assert!(has_type, "Should capture primitive type 'i32'");
    }

    // ============================================================================
    // JavaScript Highlight Tests
    // ============================================================================

    #[test]
    fn test_get_highlights_javascript_keywords() {
        let source = "function greet() {\n    return 'hello';\n}";
        let result = get_highlights(source, "javascript");

        assert!(result.success);
        assert_eq!(result.language, "javascript");

        // Check for function keyword
        let has_function = result.captures.iter().any(|c| {
            c.text(source).map_or(false, |t| t == "function")
                && (c.capture_name == "keyword" || c.capture_name.contains("function"))
        });
        assert!(has_function, "Should capture 'function' keyword");

        // Check for return keyword
        let has_return = result.captures.iter().any(|c| {
            c.text(source).map_or(false, |t| t == "return")
                && (c.capture_name == "keyword" || c.capture_name.contains("control"))
        });
        assert!(has_return, "Should capture 'return' keyword");
    }

    #[test]
    fn test_get_highlights_javascript_string() {
        let source = "const msg = 'hello world';";
        let result = get_highlights(source, "javascript");

        assert!(result.success);

        // Look for string capture
        let has_string = result.captures.iter().any(|c| {
            c.capture_name == "string" && c.text(source).map_or(false, |t| t.contains("hello"))
        });
        assert!(has_string, "Should capture string literal");
    }

    // ============================================================================
    // TypeScript Highlight Tests
    // ============================================================================

    #[test]
    fn test_get_highlights_typescript_interface() {
        let source = "interface User {\n    name: string;\n}";
        let result = get_highlights(source, "typescript");

        assert!(result.success);
        assert_eq!(result.language, "typescript");

        // Check for interface keyword
        let has_interface = result.captures.iter().any(|c| {
            c.text(source).map_or(false, |t| t == "interface")
                && (c.capture_name == "keyword" || c.capture_name.contains("keyword"))
        });
        assert!(has_interface, "Should capture 'interface' keyword");
    }

    #[test]
    fn test_get_highlights_typescript_type() {
        let source = "type ID = string;";
        let result = get_highlights(source, "typescript");

        assert!(result.success);

        // Check for type keyword
        let has_type = result.captures.iter().any(|c| {
            c.text(source).map_or(false, |t| t == "type")
                && (c.capture_name == "keyword" || c.capture_name.contains("keyword"))
        });
        assert!(has_type, "Should capture 'type' keyword");
    }

    // ============================================================================
    // Error Handling Tests
    // ============================================================================

    #[test]
    fn test_get_highlights_unsupported_language() {
        let source = "some code";
        let result = get_highlights(source, "unsupported");

        assert!(!result.success);
        assert!(!result.errors.is_empty());
        assert!(result
            .errors[0]
            .to_lowercase()
            .contains("unsupported"));
    }

    #[test]
    fn test_get_highlights_empty_source() {
        let result = get_highlights("", "python");

        assert!(result.success);
        // Empty source should have minimal or no captures
    }

    #[test]
    fn test_get_highlights_comment_only() {
        let source = "# Just a comment";
        let result = get_highlights(source, "python");

        assert!(result.success);

        let has_comment = result.captures.iter().any(|c| c.capture_name == "comment");
        assert!(has_comment, "Should capture comment in comment-only file");
    }

    #[test]
    fn test_get_highlights_elixir() {
        let source = "defmodule MyModule do\n    def hello do\n        :world\n    end\nend";
        let result = get_highlights(source, "elixir");

        assert!(result.success);
        assert_eq!(result.language, "elixir");

        // Should have some captures
        assert!(!result.captures.is_empty());
    }

    #[test]
    fn test_get_highlights_tsx() {
        let source = "const Component = () => <div>Hello</div>;";
        let result = get_highlights(source, "tsx");

        assert!(result.success);
        assert_eq!(result.language, "tsx");

        // Should have some captures
        assert!(!result.captures.is_empty());
    }

    // ============================================================================
    // HighlightContext Tests
    // ============================================================================

    #[test]
    fn test_highlight_context_new() {
        let ctx = HighlightContext::new("python");
        assert!(ctx.is_ok());

        let ctx = ctx.unwrap();
        assert_eq!(ctx.language_name(), "python");
        assert!(!ctx.capture_names().is_empty());
    }

    #[test]
    fn test_highlight_context_unsupported() {
        let ctx = HighlightContext::new("unsupported");
        assert!(ctx.is_err());
    }

    #[test]
    fn test_highlight_context_reuse() {
        let ctx = HighlightContext::new("python").unwrap();

        // First highlight
        let result1 = ctx.get_highlights("def foo(): pass");
        assert!(result1.success);

        // Second highlight (reusing query)
        let result2 = ctx.get_highlights("class Bar: pass");
        assert!(result2.success);

        // Both should work
        assert!(!result1.captures.is_empty());
        assert!(!result2.captures.is_empty());
    }

    // ============================================================================
    // File Highlight Tests
    // ============================================================================

    #[test]
    fn test_get_highlights_from_file_with_language() {
        // Create a temporary file
        let temp_dir = std::env::temp_dir();
        let temp_file = temp_dir.join("test_highlight.py");
        std::fs::write(&temp_file, "def hello():\n    pass\n").unwrap();

        let result = get_highlights_from_file(temp_file.to_str().unwrap(), Some("python"));
        assert!(result.success);
        assert!(!result.captures.is_empty());

        // Clean up
        let _ = std::fs::remove_file(&temp_file);
    }

    #[test]
    fn test_get_highlights_from_file_auto_detect() {
        // Create a temporary file
        let temp_dir = std::env::temp_dir();
        let temp_file = temp_dir.join("test_highlight.rs");
        std::fs::write(&temp_file, "fn main() {}\n").unwrap();

        let result = get_highlights_from_file(temp_file.to_str().unwrap(), None);
        assert!(result.success);
        assert_eq!(result.language, "rust");
        assert!(!result.captures.is_empty());

        // Clean up
        let _ = std::fs::remove_file(&temp_file);
    }

    #[test]
    fn test_get_highlights_from_file_not_found() {
        let result = get_highlights_from_file("/nonexistent/path/file.py", None);
        assert!(!result.success);
        assert!(!result.errors.is_empty());
    }

    #[test]
    fn test_get_highlights_from_file_unknown_extension() {
        let temp_dir = std::env::temp_dir();
        let temp_file = temp_dir.join("test_highlight.xyz");
        std::fs::write(&temp_file, "some content").unwrap();

        let result = get_highlights_from_file(temp_file.to_str().unwrap(), None);
        assert!(!result.success);
        assert!(!result.errors.is_empty());

        // Clean up
        let _ = std::fs::remove_file(&temp_file);
    }

    // ============================================================================
    // Language Alias Tests
    // ============================================================================

    #[test]
    fn test_get_highlights_py_alias() {
        let source = "def hello(): pass";
        let result = get_highlights(source, "py");
        assert!(result.success);
        assert_eq!(result.language, "python");
    }

    #[test]
    fn test_get_highlights_js_alias() {
        let source = "function hello() {}";
        let result = get_highlights(source, "js");
        assert!(result.success);
        assert_eq!(result.language, "javascript");
    }

    #[test]
    fn test_get_highlights_ts_alias() {
        let source = "function hello(): void {}";
        let result = get_highlights(source, "ts");
        assert!(result.success);
        assert_eq!(result.language, "typescript");
    }

    #[test]
    fn test_get_highlights_ex_alias() {
        let source = "defmodule Hello do end";
        let result = get_highlights(source, "ex");
        assert!(result.success);
        assert_eq!(result.language, "elixir");
    }

    #[test]
    fn test_get_highlights_exs_alias() {
        let source = "defmodule Hello do end";
        let result = get_highlights(source, "exs");
        assert!(result.success);
        assert_eq!(result.language, "elixir");
    }
}
