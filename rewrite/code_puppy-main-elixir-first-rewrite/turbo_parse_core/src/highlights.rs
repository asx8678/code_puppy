//! Syntax highlighting query runner using tree-sitter queries.
//!
//! Provides extraction of syntax highlighting regions from source code
//! using the vendored Helix Editor queries/highlights.scm files.

use std::time::Instant;
use streaming_iterator::StreamingIterator;
use tree_sitter::{Language, Parser, Query, QueryCursor};

use crate::queries::{get_highlights_query, normalize_language};
use crate::registry::get_language;
use crate::types::{HighlightCapture, HighlightResult};

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
    pub fn new(language_name: &str) -> Result<Self, String> {
        let lang_name = normalize_language(language_name);

        // Get the tree-sitter language
        let ts_language = get_language(&lang_name).map_err(|e| e.to_string())?;

        // Get the highlights query
        let query_str = get_highlights_query(&lang_name)
            .map_err(|e| format!("Failed to load highlights query: {}", e))?;

        // Parse the query
        let query = Query::new(&ts_language, query_str)
            .map_err(|e| format!("Query error: {:?}", e))?;

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
                    (*capture_name).to_string(),
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
            HighlightCapture::new(0, 10, "keyword.control"),
        ];

        let merged = merge_overlapping_captures(caps);

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

    #[test]
    fn test_get_highlights_python_keywords() {
        let source = "def hello():\n    pass";
        let result = get_highlights(source, "python");

        assert!(result.success);
        assert_eq!(result.language, "python");

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

        let has_string = result.captures.iter().any(|c| {
            c.capture_name == "string" && c.text(source).map_or(false, |t| t.contains("hello"))
        });
        assert!(has_string, "Should capture string literal");
    }

    #[test]
    fn test_get_highlights_rust_keywords() {
        let source = "fn main() {\n    let x = 42;\n}";
        let result = get_highlights(source, "rust");

        assert!(result.success);
        assert_eq!(result.language, "rust");

        let has_fn = result.captures.iter().any(|c| {
            c.text(source).map_or(false, |t| t == "fn")
                && (c.capture_name == "keyword" || c.capture_name.contains("function"))
        });
        assert!(has_fn, "Should capture 'fn' keyword");
    }

    #[test]
    fn test_get_highlights_unsupported_language() {
        let source = "some code";
        let result = get_highlights(source, "unsupported");

        assert!(!result.success);
        assert!(!result.errors.is_empty());
    }

    #[test]
    fn test_get_highlights_empty_source() {
        let result = get_highlights("", "python");

        assert!(result.success);
    }

    #[test]
    fn test_get_highlights_elixir() {
        let source = "defmodule MyModule do\n    def hello do\n        :world\n    end\nend";
        let result = get_highlights(source, "elixir");

        assert!(result.success);
        assert_eq!(result.language, "elixir");
        assert!(!result.captures.is_empty());
    }

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

        let result1 = ctx.get_highlights("def foo(): pass");
        assert!(result1.success);

        let result2 = ctx.get_highlights("class Bar: pass");
        assert!(result2.success);

        assert!(!result1.captures.is_empty());
        assert!(!result2.captures.is_empty());
    }

    #[test]
    fn test_get_highlights_from_file_not_found() {
        let result = get_highlights_from_file("/nonexistent/path/file.py", None);
        assert!(!result.success);
        assert!(!result.errors.is_empty());
    }
}
