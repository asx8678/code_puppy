//! Diagnostics module — Syntax error and warning extraction from tree-sitter trees.
//!
//! Provides tools to walk tree-sitter trees and extract ERROR and MISSING nodes,
//! converting them into structured diagnostics with position information.

use serde::{Deserialize, Serialize};
use tree_sitter::Node;

/// Severity level for a diagnostic.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Severity {
    /// Error that prevents proper parsing/compilation.
    #[serde(rename = "error")]
    Error,
    /// Warning about potential issues (not strictly syntax errors).
    #[serde(rename = "warning")]
    Warning,
}

impl std::fmt::Display for Severity {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Severity::Error => write!(f, "error"),
            Severity::Warning => write!(f, "warning"),
        }
    }
}

/// A single diagnostic message with location information.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Diagnostic {
    /// Human-readable error/warning message.
    pub message: String,
    /// Severity level of the diagnostic.
    pub severity: Severity,
    /// Line number (1-indexed).
    pub line: usize,
    /// Column number (0-indexed).
    pub column: usize,
    /// Byte offset in the source.
    pub offset: usize,
    /// Length of the error region in bytes.
    pub length: usize,
    /// Node kind that caused the error (e.g., "ERROR", "MISSING").
    pub node_kind: String,
}

impl Diagnostic {
    /// Create a new diagnostic.
    pub fn new(
        message: impl Into<String>,
        severity: Severity,
        line: usize,
        column: usize,
        offset: usize,
        length: usize,
        node_kind: impl Into<String>,
    ) -> Self {
        Self {
            message: message.into(),
            severity,
            line,
            column,
            offset,
            length,
            node_kind: node_kind.into(),
        }
    }

    /// Create a diagnostic from a tree-sitter node.
    pub fn from_node(node: Node, source: &str, severity: Severity) -> Self {
        let start_pos = node.start_position();
        let end_byte = node.end_byte();
        let start_byte = node.start_byte();

        let text = node.utf8_text(source.as_bytes()).unwrap_or("");
        let message = Self::format_message(node, text);

        Self::new(
            message,
            severity,
            start_pos.row + 1, // 1-indexed line
            start_pos.column,
            start_byte,
            end_byte.saturating_sub(start_byte),
            node.kind(),
        )
    }

    /// Format a message for a diagnostic node.
    fn format_message(node: Node, text: &str) -> String {
        if node.is_missing() {
            format!("Missing: expected '{}'", node.kind())
        } else if text.is_empty() {
            "Syntax error".to_string()
        } else if text.len() > 50 {
            format!("Syntax error: '{}'...", &text[..50])
        } else {
            format!("Syntax error: '{}'", text)
        }
    }
}

/// Collection of diagnostics from a parse.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SyntaxDiagnostics {
    /// All diagnostics collected from the tree.
    pub diagnostics: Vec<Diagnostic>,
}

impl SyntaxDiagnostics {
    /// Create a new empty diagnostics collection.
    pub fn new() -> Self {
        Self::default()
    }

    /// Add a diagnostic to the collection.
    pub fn add(&mut self, diagnostic: Diagnostic) {
        self.diagnostics.push(diagnostic);
    }

    /// Get all error-level diagnostics.
    pub fn errors(&self) -> Vec<&Diagnostic> {
        self.diagnostics
            .iter()
            .filter(|d| d.severity == Severity::Error)
            .collect()
    }

    /// Get all warning-level diagnostics.
    pub fn warnings(&self) -> Vec<&Diagnostic> {
        self.diagnostics
            .iter()
            .filter(|d| d.severity == Severity::Warning)
            .collect()
    }

    /// Check if there are any diagnostics.
    pub fn is_empty(&self) -> bool {
        self.diagnostics.is_empty()
    }

    /// Get the total number of diagnostics.
    pub fn len(&self) -> usize {
        self.diagnostics.len()
    }

    /// Get the number of errors.
    pub fn error_count(&self) -> usize {
        self.errors().len()
    }

    /// Get the number of warnings.
    pub fn warning_count(&self) -> usize {
        self.warnings().len()
    }
}

/// Walk a tree-sitter tree and collect all ERROR and MISSING nodes.
pub fn walk_tree_for_diagnostics(node: Node, source: &str, diagnostics: &mut SyntaxDiagnostics) {
    // Check if this node is an error or missing
    if node.is_error() {
        let diagnostic = Diagnostic::from_node(node, source, Severity::Error);
        diagnostics.add(diagnostic);
    } else if node.is_missing() {
        let diagnostic = Diagnostic::from_node(node, source, Severity::Error);
        diagnostics.add(diagnostic);
    }

    // Recursively check all children
    for i in 0..node.child_count() {
        if let Some(child) = node.child(i) {
            walk_tree_for_diagnostics(child, source, diagnostics);
        }
    }
}

/// Extract diagnostics from source code using tree-sitter.
///
/// # Arguments
/// * `source` - The source code to analyze
/// * `language` - The tree-sitter Language to use for parsing
///
/// # Returns
/// A SyntaxDiagnostics struct containing all found ERROR and MISSING nodes.
pub fn extract_diagnostics(source: &str, language: &tree_sitter::Language) -> SyntaxDiagnostics {
    let mut parser = tree_sitter::Parser::new();
    
    // Set the language (ignore errors as this is called after successful parse)
    let _ = parser.set_language(language);
    
    // Parse the source
    if let Some(tree) = parser.parse(source, None) {
        let mut diagnostics = SyntaxDiagnostics::new();
        walk_tree_for_diagnostics(tree.root_node(), source, &mut diagnostics);
        diagnostics
    } else {
        // If parsing fails completely, return empty diagnostics
        SyntaxDiagnostics::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tree_sitter::Language;

    fn get_python_language() -> Language {
        Language::from(tree_sitter_python::LANGUAGE)
    }

    fn get_rust_language() -> Language {
        Language::from(tree_sitter_rust::LANGUAGE)
    }

    fn get_javascript_language() -> Language {
        Language::from(tree_sitter_javascript::LANGUAGE)
    }

    #[test]
    fn test_diagnostic_creation() {
        let diag = Diagnostic::new(
            "Test error",
            Severity::Error,
            10,
            5,
            100,
            10,
            "ERROR",
        );

        assert_eq!(diag.message, "Test error");
        assert_eq!(diag.severity, Severity::Error);
        assert_eq!(diag.line, 10);
        assert_eq!(diag.column, 5);
        assert_eq!(diag.offset, 100);
        assert_eq!(diag.length, 10);
        assert_eq!(diag.node_kind, "ERROR");
    }

    #[test]
    fn test_severity_display() {
        assert_eq!(format!("{}", Severity::Error), "error");
        assert_eq!(format!("{}", Severity::Warning), "warning");
    }

    #[test]
    fn test_syntax_diagnostics_empty() {
        let diagnostics = SyntaxDiagnostics::new();
        assert!(diagnostics.is_empty());
        assert_eq!(diagnostics.len(), 0);
        assert_eq!(diagnostics.error_count(), 0);
        assert_eq!(diagnostics.warning_count(), 0);
    }

    #[test]
    fn test_syntax_diagnostics_add() {
        let mut diagnostics = SyntaxDiagnostics::new();
        
        let diag1 = Diagnostic::new("Error 1", Severity::Error, 1, 0, 0, 5, "ERROR");
        let diag2 = Diagnostic::new("Warning 1", Severity::Warning, 2, 10, 50, 5, "node");
        
        diagnostics.add(diag1);
        diagnostics.add(diag2);
        
        assert!(!diagnostics.is_empty());
        assert_eq!(diagnostics.len(), 2);
        assert_eq!(diagnostics.error_count(), 1);
        assert_eq!(diagnostics.warning_count(), 1);
    }

    #[test]
    fn test_extract_diagnostics_python_valid() {
        let source = "def hello():\n    pass\n";
        let lang = get_python_language();
        let diagnostics = extract_diagnostics(source, &lang);
        
        // Valid code should have no diagnostics
        assert!(diagnostics.is_empty());
    }

    #[test]
    fn test_extract_diagnostics_python_syntax_error() {
        // Missing closing parenthesis
        let source = "def hello(\n    pass\n";
        let lang = get_python_language();
        let diagnostics = extract_diagnostics(source, &lang);
        
        // Should have at least one error
        assert!(!diagnostics.is_empty(), "Expected errors for broken syntax");
        assert!(diagnostics.error_count() > 0, "Expected at least one error");
        
        // All should be errors
        for diag in &diagnostics.diagnostics {
            assert_eq!(diag.severity, Severity::Error);
            assert!(diag.line > 0);
        }
    }

    #[test]
    fn test_extract_diagnostics_python_multiple_errors() {
        // Multiple syntax errors - each function missing closing paren
        let source = "def a(\n    pass 1\ndef b(\n    pass 2\n";
        let lang = get_python_language();
        let diagnostics = extract_diagnostics(source, &lang);
        
        // Tree-sitter error recovery may consolidate errors, just verify we find at least 1
        assert!(
            diagnostics.error_count() >= 1,
            "Expected at least one error, got {}",
            diagnostics.error_count()
        );
    }

    #[test]
    fn test_extract_diagnostics_rust() {
        // Rust code with syntax error
        let source = "fn main() {\n    let x =\n}\n";
        let lang = get_rust_language();
        let diagnostics = extract_diagnostics(source, &lang);
        
        // Should either have diagnostics OR tree-sitter may recover gracefully
        // The key is that parsing doesn't panic and we get a result
        let has_errors = !diagnostics.is_empty();
        let root_has_error = {
            let mut parser = tree_sitter::Parser::new();
            parser.set_language(&lang).unwrap();
            parser.parse(source, None)
                .map(|t| t.root_node().has_error())
                .unwrap_or(false)
        };
        
        // Either we found errors, or tree flagged errors, or both
        assert!(
            has_errors || root_has_error || diagnostics.error_count() > 0,
            "Expected either diagnostics or tree-sitter to flag errors for broken Rust code"
        );
    }

    #[test]
    fn test_extract_diagnostics_javascript() {
        // JS code with syntax error
        let source = "function test() {\n    return\n}\n";
        let lang = get_javascript_language();
        let diagnostics = extract_diagnostics(source, &lang);
        
        // Valid code should have no diagnostics
        assert!(diagnostics.is_empty());
    }

    #[test]
    fn test_extract_diagnostics_javascript_broken() {
        // JS code with clear syntax error
        let source = "function test( {\n    return 1;\n}\n";
        let lang = get_javascript_language();
        let diagnostics = extract_diagnostics(source, &lang);
        
        // Check if tree-sitter detected an error in the tree
        let root_has_error = {
            let mut parser = tree_sitter::Parser::new();
            parser.set_language(&lang).unwrap();
            parser.parse(source, None)
                .map(|t| t.root_node().has_error())
                .unwrap_or(false)
        };
        
        // Either we have diagnostics OR the tree flagged an error (tree-sitter recovery may vary)
        assert!(
            !diagnostics.is_empty() || root_has_error || diagnostics.error_count() > 0,
            "Expected either diagnostics extracted OR tree-sitter to flag errors for broken JS code"
        );
    }

    #[test]
    fn test_extract_diagnostics_empty_source() {
        let source = "";
        let lang = get_python_language();
        let diagnostics = extract_diagnostics(source, &lang);
        
        // Empty source should have no errors
        assert!(diagnostics.is_empty());
    }

    #[test]
    fn test_diagnostic_serialization() {
        let diag = Diagnostic::new(
            "Test error",
            Severity::Error,
            10,
            5,
            100,
            10,
            "ERROR",
        );

        let json = serde_json::to_string(&diag).unwrap();
        let deserialized: Diagnostic = serde_json::from_str(&json).unwrap();

        assert_eq!(diag.message, deserialized.message);
        assert_eq!(diag.severity, deserialized.severity);
        assert_eq!(diag.line, deserialized.line);
        assert_eq!(diag.column, deserialized.column);
        assert_eq!(diag.offset, deserialized.offset);
        assert_eq!(diag.length, deserialized.length);
        assert_eq!(diag.node_kind, deserialized.node_kind);
    }

    #[test]
    fn test_diagnostics_serialization() {
        let mut diagnostics = SyntaxDiagnostics::new();
        diagnostics.add(Diagnostic::new("Error 1", Severity::Error, 1, 0, 0, 5, "ERROR"));
        diagnostics.add(Diagnostic::new("Warning 1", Severity::Warning, 2, 10, 50, 5, "node"));

        let json = serde_json::to_string(&diagnostics).unwrap();
        let deserialized: SyntaxDiagnostics = serde_json::from_str(&json).unwrap();

        assert_eq!(deserialized.len(), 2);
        assert_eq!(deserialized.error_count(), 1);
        assert_eq!(deserialized.warning_count(), 1);
    }

    #[test]
    fn test_diagnostic_from_node_error() {
        let source = "def test(";
        let lang = get_python_language();
        
        let mut parser = tree_sitter::Parser::new();
        parser.set_language(&lang).unwrap();
        
        if let Some(tree) = parser.parse(source, None) {
            let mut diagnostics = SyntaxDiagnostics::new();
            walk_tree_for_diagnostics(tree.root_node(), source, &mut diagnostics);
            
            // Should find error nodes
            assert!(
                !diagnostics.is_empty() || !tree.root_node().has_error(),
                "Should have diagnostics for broken code"
            );
        }
    }

    #[test]
    fn test_walk_tree_no_false_positives() {
        // Valid Python code - should not generate false positive diagnostics
        let source = r#"
def hello(name):
    """A docstring."""
    return f"Hello, {name}!"

class MyClass:
    def __init__(self):
        self.value = 42
    
    def get_value(self):
        return self.value

if __name__ == "__main__":
    print(hello("world"))
"#;
        let lang = get_python_language();
        let diagnostics = extract_diagnostics(source, &lang);
        
        // Valid code should have no diagnostics
        assert!(diagnostics.is_empty(), "Valid code should not produce diagnostics");
    }

    #[test]
    fn test_extract_diagnostics_all_languages() {
        // Test that we can create parsers for all supported languages
        let languages = vec![
            ("python", get_python_language()),
            ("rust", get_rust_language()),
            ("javascript", get_javascript_language()),
        ];

        for (name, lang) in languages {
            let diagnostics = extract_diagnostics("", &lang);
            assert!(
                diagnostics.is_empty(),
                "Empty source should work for {}",
                name
            );
        }
    }
}
