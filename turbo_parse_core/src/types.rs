//! Core types for parsing operations.
//!
//! This module defines the public types used across the turbo_parse_core crate.
//! All types are serializable with serde and contain no PyO3 dependencies.

use serde::{Deserialize, Serialize};

/// A single symbol extracted from source code.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Symbol {
    /// Name of the symbol
    pub name: String,
    /// Kind of symbol (e.g., "function", "class", "method")
    pub kind: String,
    /// Start line (1-indexed)
    pub start_line: usize,
    /// Start column (0-indexed)
    pub start_column: usize,
    /// End line (1-indexed)
    pub end_line: usize,
    /// End column (0-indexed)
    pub end_column: usize,
    /// Optional parent symbol name (for methods inside classes)
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent: Option<String>,
    /// Optional documentation/comment
    #[serde(skip_serializing_if = "Option::is_none")]
    pub docstring: Option<String>,
}

impl Symbol {
    /// Create a new symbol.
    pub fn new(
        name: impl Into<String>,
        kind: impl Into<String>,
        start_line: usize,
        start_column: usize,
        end_line: usize,
        end_column: usize,
    ) -> Self {
        Self {
            name: name.into(),
            kind: kind.into(),
            start_line,
            start_column,
            end_line,
            end_column,
            parent: None,
            docstring: None,
        }
    }

    /// Set the parent symbol.
    pub fn with_parent(mut self, parent: impl Into<String>) -> Self {
        self.parent = Some(parent.into());
        self
    }

    /// Set the docstring.
    pub fn with_docstring(mut self, docstring: impl Into<String>) -> Self {
        self.docstring = Some(docstring.into());
        self
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
    /// Syntax diagnostics from tree analysis
    pub diagnostics: SyntaxDiagnostics,
}

impl ParseResult {
    /// Create a new parse result.
    pub fn new(
        language: impl Into<String>,
        tree: Option<serde_json::Value>,
        parse_time_ms: f64,
        success: bool,
        errors: Vec<ParseError>,
        diagnostics: SyntaxDiagnostics,
    ) -> Self {
        Self {
            language: language.into(),
            tree,
            parse_time_ms,
            success,
            errors,
            diagnostics,
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
            diagnostics: SyntaxDiagnostics::new(),
        }
    }
}

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

/// Severity level for a diagnostic.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Severity {
    /// Error that prevents proper parsing/compilation.
    #[serde(rename = "error")]
    Error,
    /// Warning about potential issues.
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

    /// Get the number of diagnostics.
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

/// Collection of symbols extracted from a source file.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SymbolOutline {
    /// The programming language
    pub language: String,
    /// All symbols found in the file
    pub symbols: Vec<Symbol>,
    /// Time taken to extract symbols in milliseconds
    pub extraction_time_ms: f64,
    /// Whether the extraction succeeded
    pub success: bool,
    /// Any errors encountered during extraction
    pub errors: Vec<String>,
}

impl SymbolOutline {
    /// Create a new symbol outline.
    pub fn new(
        language: impl Into<String>,
        symbols: Vec<Symbol>,
        extraction_time_ms: f64,
        success: bool,
    ) -> Self {
        Self {
            language: language.into(),
            symbols,
            extraction_time_ms,
            success,
            errors: Vec::new(),
        }
    }

    /// Create an error result.
    pub fn error(language: impl Into<String>, error: impl Into<String>) -> Self {
        Self {
            language: language.into(),
            symbols: Vec::new(),
            extraction_time_ms: 0.0,
            success: false,
            errors: vec![error.into()],
        }
    }

    /// Get symbols of a specific kind.
    pub fn symbols_of_kind(&self, kind: &str) -> Vec<&Symbol> {
        self.symbols.iter().filter(|s| s.kind == kind).collect()
    }

    /// Get top-level symbols (those without a parent).
    pub fn top_level_symbols(&self) -> Vec<&Symbol> {
        self.symbols.iter().filter(|s| s.parent.is_none()).collect()
    }
}

/// Type of foldable region.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FoldType {
    /// Function definition
    Function,
    /// Class/struct definition
    Class,
    /// Conditional block (if, else, match, etc.)
    Conditional,
    /// Loop construct (for, while, loop)
    Loop,
    /// Block statement (try, with, etc.)
    Block,
    /// Import/export statement
    Import,
    /// Generic block (object, array, etc.)
    Generic,
}

impl std::fmt::Display for FoldType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            FoldType::Function => "function",
            FoldType::Class => "class",
            FoldType::Conditional => "conditional",
            FoldType::Loop => "loop",
            FoldType::Block => "block",
            FoldType::Import => "import",
            FoldType::Generic => "generic",
        };
        write!(f, "{}", s)
    }
}

/// A single foldable region in source code.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FoldRange {
    /// Start line (1-indexed)
    pub start_line: usize,
    /// End line (1-indexed)
    pub end_line: usize,
    /// Type of foldable region
    pub fold_type: FoldType,
    /// Tree-sitter node kind for debugging
    #[serde(skip_serializing_if = "Option::is_none")]
    pub node_kind: Option<String>,
}

impl FoldRange {
    /// Create a new fold range.
    pub fn new(start_line: usize, end_line: usize, fold_type: FoldType) -> Self {
        Self {
            start_line,
            end_line,
            fold_type,
            node_kind: None,
        }
    }

    /// Set the node kind for debugging.
    pub fn with_node_kind(mut self, kind: impl Into<String>) -> Self {
        self.node_kind = Some(kind.into());
        self
    }
}

/// Result of fold extraction from source code.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FoldResult {
    /// The programming language
    pub language: String,
    /// All fold ranges found in the file
    pub folds: Vec<FoldRange>,
    /// Time taken to extract folds in milliseconds
    pub extraction_time_ms: f64,
    /// Whether the extraction succeeded
    pub success: bool,
    /// Any errors encountered during extraction
    pub errors: Vec<String>,
}

impl FoldResult {
    /// Create a new fold result.
    pub fn new(language: impl Into<String>, folds: Vec<FoldRange>, extraction_time_ms: f64) -> Self {
        Self {
            language: language.into(),
            folds,
            extraction_time_ms,
            success: true,
            errors: Vec::new(),
        }
    }

    /// Create an error result.
    pub fn error(language: impl Into<String>, error: impl Into<String>) -> Self {
        Self {
            language: language.into(),
            folds: Vec::new(),
            extraction_time_ms: 0.0,
            success: false,
            errors: vec![error.into()],
        }
    }

    /// Get folds of a specific type.
    pub fn folds_of_type(&self, fold_type: &FoldType) -> Vec<&FoldRange> {
        self.folds.iter().filter(|f| f.fold_type == *fold_type).collect()
    }

    /// Get the number of folds.
    pub fn count(&self) -> usize {
        self.folds.len()
    }
}

/// A single highlight capture region.
///
/// Represents a syntax-highlightable region of source code with
/// its byte position and capture name (e.g., "keyword", "string").
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
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

/// Errors that can occur when working with the language registry.
#[derive(Debug, Clone, PartialEq, thiserror::Error)]
pub enum RegistryError {
    /// The requested language is not supported.
    #[error("Unsupported language: '{0}'")]
    UnsupportedLanguage(String),
    /// Failed to initialize the language grammar.
    #[error("Failed to initialize language: {0}")]
    InitializationError(String),
    /// Dynamic loading is not available for this language.
    #[error("Dynamic grammar loading is disabled")]
    DynamicLoadingDisabled,
}

/// Errors that can occur when loading queries.
#[derive(Debug, Clone, PartialEq, thiserror::Error)]
pub enum QueryError {
    /// The specified language is not supported.
    #[error("Unsupported language: '{0}'")]
    UnsupportedLanguage(String),
    /// The specified query type is not available for this language.
    #[error("Query type '{query_type}' not available for language '{language}'")]
    QueryTypeNotAvailable { language: String, query_type: String },
}

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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_symbol_new() {
        let sym = Symbol::new("test", "function", 1, 0, 10, 5);
        assert_eq!(sym.name, "test");
        assert_eq!(sym.kind, "function");
        assert_eq!(sym.start_line, 1);
        assert_eq!(sym.end_line, 10);
        assert!(sym.parent.is_none());
    }

    #[test]
    fn test_symbol_with_parent() {
        let sym = Symbol::new("method", "method", 2, 4, 5, 15)
            .with_parent("MyClass");
        assert_eq!(sym.parent, Some("MyClass".to_string()));
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
    fn test_diagnostic_creation() {
        let diag = Diagnostic::new("test", Severity::Error, 1, 0, 0, 5, "ERROR");
        assert_eq!(diag.message, "test");
        assert_eq!(diag.severity, Severity::Error);
        assert_eq!(diag.line, 1);
    }

    #[test]
    fn test_fold_type_display() {
        assert_eq!(format!("{}", FoldType::Function), "function");
        assert_eq!(format!("{}", FoldType::Class), "class");
    }

    #[test]
    fn test_fold_range_new() {
        let fold = FoldRange::new(1, 10, FoldType::Function);
        assert_eq!(fold.start_line, 1);
        assert_eq!(fold.end_line, 10);
        assert_eq!(fold.fold_type, FoldType::Function);
    }

    #[test]
    fn test_highlight_capture() {
        let cap = HighlightCapture::new(0, 5, "keyword");
        assert_eq!(cap.start_byte, 0);
        assert_eq!(cap.end_byte, 5);
        assert_eq!(cap.capture_name, "keyword");
        assert_eq!(cap.len(), 5);
        assert!(!cap.is_empty());
    }

    #[test]
    fn test_highlight_capture_text() {
        let source = "def hello(): pass";
        let cap = HighlightCapture::new(0, 3, "keyword");
        assert_eq!(cap.text(source), Some("def"));
    }

    #[test]
    fn test_highlight_capture_overlaps() {
        let cap1 = HighlightCapture::new(0, 5, "keyword");
        let cap2 = HighlightCapture::new(3, 8, "variable");
        let cap3 = HighlightCapture::new(10, 15, "string");

        assert!(cap1.overlaps(&cap2));
        assert!(!cap1.overlaps(&cap3));
    }

    #[test]
    fn test_severity_display() {
        assert_eq!(format!("{}", Severity::Error), "error");
        assert_eq!(format!("{}", Severity::Warning), "warning");
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
}
