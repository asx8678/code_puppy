//! Incremental parsing module — Edit-aware re-parsing with tree-sitter.
//!
//! Provides incremental parsing capabilities that reuse previous parse trees
//! when only small changes have been made to the source code.
//!
//! This is significantly faster than full re-parsing for editor-like use cases
//! where users make small, localized edits.

use serde::{Deserialize, Serialize};
use std::time::Instant;
use tree_sitter::{InputEdit as TSInputEdit, Node, Parser, Point, Tree};

use crate::diagnostics::extract_diagnostics;
use crate::parser::{ParseError, ParseResult};
use crate::registry::{get_language, normalize_language, RegistryError};

#[cfg(feature = "python")]
use pyo3::prelude::*;

/// Describes a text edit for incremental parsing.
#[cfg(feature = "python")]
#[pyclass(frozen)]
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct InputEdit {
    /// Byte offset where the edit starts in the old document
    #[pyo3(get)]
    pub start_byte: usize,
    /// Byte offset where the replaced region ended in the old document
    #[pyo3(get)]
    pub old_end_byte: usize,
    /// Byte offset where the new text ends in the new document
    #[pyo3(get)]
    pub new_end_byte: usize,
    /// Line and column where the edit starts (row, column)
    #[pyo3(get)]
    pub start_position: (usize, usize),
    /// Line and column where the replaced region ended (row, column)
    #[pyo3(get)]
    pub old_end_position: (usize, usize),
    /// Line and column where the new text ends (row, column)
    #[pyo3(get)]
    pub new_end_position: (usize, usize),
}

/// Describes a text edit for incremental parsing (without python feature).
#[cfg(not(feature = "python"))]
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct InputEdit {
    /// Byte offset where the edit starts in the old document
    pub start_byte: usize,
    /// Byte offset where the replaced region ended in the old document
    pub old_end_byte: usize,
    /// Byte offset where the new text ends in the new document
    pub new_end_byte: usize,
    /// Line and column where the edit starts (row, column)
    pub start_position: (usize, usize),
    /// Line and column where the replaced region ended (row, column)
    pub old_end_position: (usize, usize),
    /// Line and column where the new text ends (row, column)
    pub new_end_position: (usize, usize),
}

impl InputEdit {
    /// Create a new InputEdit describing a text change.
    pub fn new(
        start_byte: usize,
        old_end_byte: usize,
        new_end_byte: usize,
        start_position: (usize, usize),
        old_end_position: (usize, usize),
        new_end_position: (usize, usize),
    ) -> Self {
        Self {
            start_byte,
            old_end_byte,
            new_end_byte,
            start_position,
            old_end_position,
            new_end_position,
        }
    }

    /// Convert to tree-sitter's native InputEdit type.
    pub fn to_ts_edit(&self) -> TSInputEdit {
        TSInputEdit {
            start_byte: self.start_byte,
            old_end_byte: self.old_end_byte,
            new_end_byte: self.new_end_byte,
            start_position: Point::new(self.start_position.0, self.start_position.1),
            old_end_position: Point::new(self.old_end_position.0, self.old_end_position.1),
            new_end_position: Point::new(self.new_end_position.0, self.new_end_position.1),
        }
    }
}

#[cfg(feature = "python")]
mod python_impl {
    use super::*;
    use pyo3::prelude::{PyResult, Python, Bound, PyAny};
    use pyo3::pymethods;

    #[pymethods]
    impl InputEdit {
        #[new]
        #[pyo3(signature = (start_byte, old_end_byte, new_end_byte, start_position, old_end_position, new_end_position))]
        fn py_new(
            start_byte: usize,
            old_end_byte: usize,
            new_end_byte: usize,
            start_position: (usize, usize),
            old_end_position: (usize, usize),
            new_end_position: (usize, usize),
        ) -> Self {
            Self::new(
                start_byte,
                old_end_byte,
                new_end_byte,
                start_position,
                old_end_position,
                new_end_position,
            )
        }

        fn to_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
            let dict = serde_json::json!({
                "start_byte": self.start_byte,
                "old_end_byte": self.old_end_byte,
                "new_end_byte": self.new_end_byte,
                "start_position": self.start_position,
                "old_end_position": self.old_end_position,
                "new_end_position": self.new_end_position,
            });

            let json_str = serde_json::to_string(&dict)
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;

            let json_module = py.import("json")?;
            let py_dict = json_module.call_method1("loads", (json_str,))?;
            Ok(py_dict)
        }

        fn __repr__(&self) -> String {
            format!(
                "InputEdit(start_byte={}, old_end_byte={}, new_end_byte={}, start_position={:?}, old_end_position={:?}, new_end_position={:?})",
                self.start_byte, self.old_end_byte, self.new_end_byte,
                self.start_position, self.old_end_position, self.new_end_position,
            )
        }

        fn __eq__(&self, other: &Self) -> bool {
            self == other
        }
    }
}

/// Serialized tree data used to reconstruct a Tree for incremental parsing.
#[cfg(feature = "python")]
#[pyclass(frozen)]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SerializedTree {
    /// The language identifier
    #[pyo3(get)]
    pub language: String,
    /// The source code that was parsed
    #[pyo3(get)]
    pub source: String,
    /// Whether the tree had errors
    #[pyo3(get)]
    pub had_errors: bool,
}

/// Serialized tree data used to reconstruct a Tree (without python feature).
#[cfg(not(feature = "python"))]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SerializedTree {
    /// The language identifier
    pub language: String,
    /// The source code that was parsed
    pub source: String,
    /// Whether the tree had errors
    pub had_errors: bool,
}

impl SerializedTree {
    /// Create a new serialized tree reference.
    pub fn new(language: String, source: String, had_errors: bool) -> Self {
        Self {
            language,
            source,
            had_errors,
        }
    }
}

#[cfg(feature = "python")]
#[pymethods]
impl SerializedTree {
    /// Create a new serialized tree reference (Python constructor).
    #[new]
    #[pyo3(signature = (language, source, had_errors = false))]
    fn py_new(language: String, source: String, had_errors: bool) -> Self {
        Self::new(language, source, had_errors)
    }
}

/// Internal representation of tree data for incremental parsing.
///
/// Since tree-sitter Trees cannot be fully serialized, we store the
/// source code and re-parse to get a Tree that we can then edit.
/// For true incremental benefits, maintain the Tree in memory.
pub struct IncrementalParseContext {
    /// The tree-sitter tree (can be None if we need to re-parse)
    pub tree: Option<Tree>,
    /// The source code at time of last parse
    pub source: String,
    /// The language used for parsing
    pub language: String,
}

impl IncrementalParseContext {
    /// Create a new context from a full parse.
    pub fn new(tree: Tree, source: String, language: String) -> Self {
        Self {
            tree: Some(tree),
            source,
            language,
        }
    }

    /// Apply an edit to the stored tree (for in-memory incremental parsing).
    pub fn apply_edit(&mut self, edit: &InputEdit) {
        if let Some(ref mut tree) = self.tree {
            tree.edit(&edit.to_ts_edit());
        }
    }
}

/// Parse source code incrementally, reusing an existing tree.
///
/// This function applies edits to an existing parse tree and then
/// re-parses, allowing tree-sitter to efficiently update only the
/// affected parts of the tree. This is much faster than full re-parsing
/// for small edits.
///
/// # Arguments
/// * `source` - The new source code after edits
/// * `language` - The language identifier (e.g., "python", "rust")
/// * `old_tree` - Optional tree from previous parse (from context.tree)
/// * `edits` - List of InputEdit describing the changes
///
/// # Returns
/// ParseResult with updated tree and timing information.
///
/// # Example
/// ```python
/// import turbo_parse
///
/// # Initial parse
/// source = "def hello(): pass"
/// result = turbo_parse.parse_source(source, "python")
///
/// # Make an edit: change to "def hello(): return 42"
/// new_source = "def hello(): return 42"
/// edit = turbo_parse.InputEdit(
///     start_byte=14,
///     old_end_byte=18,
///     new_end_byte=24,
///     start_position=(0, 14),
///     old_end_position=(0, 18),
///     new_end_position=(0, 24)
/// )
///
/// # Incremental re-parse
/// new_result = turbo_parse.parse_with_edits(
///     new_source,
///     "python",
///     result["tree"],
///     [edit]
/// )
/// ```
pub fn parse_with_edits_internal(
    source: &str,
    language: &str,
    old_tree: Option<&Tree>,
    edits: &[InputEdit],
) -> ParseResult {
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

    if let Err(e) = parser.set_language(&ts_language) {
        return ParseResult::error(
            &lang_name,
            ParseError::with_message(format!("Failed to set language: {}", e))
        );
    }

    // If we have an old tree, apply edits to it and use for incremental parsing
    let tree_result = if let Some(old_tree) = old_tree {
        // Clone the old tree so we can edit it
        let mut edited_tree = old_tree.clone();

        // Apply all edits to the tree
        for edit in edits {
            edited_tree.edit(&edit.to_ts_edit());
        }

        // Parse with the edited old tree for incremental parsing
        parser.parse(source, Some(&edited_tree))
    } else {
        // No old tree, do a fresh parse
        parser.parse(source, None)
    };

    let parse_time_ms = start.elapsed().as_secs_f64() * 1000.0;

    // Get the resulting tree
    let tree = match tree_result {
        Some(t) => t,
        None => {
            return ParseResult::error(
                &lang_name,
                ParseError::with_message("Parser returned no tree")
            );
        }
    };

    // Extract diagnostics from the tree
    let diagnostics = extract_diagnostics(source, &ts_language);

    // Check for errors
    let has_errors = !diagnostics.is_empty() || tree.root_node().has_error();

    // Serialize the tree
    let tree_json = serialize_tree(&tree, source);

    ParseResult::new(
        &lang_name,
        Some(tree_json),
        parse_time_ms,
        !has_errors,
        Vec::new(),  // Legacy errors
        diagnostics,
    )
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

    // Extract text if node is small enough
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

/// Python-exposed function for incremental parsing with edits.
///
/// NOTE: This function currently performs a fresh parse for each call.
/// True incremental parsing with explicit old tree passing is not yet
/// supported via Python. For incremental benefits, use `IncrementalParseContext`
/// in Rust code or the internal caching layer in Python.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (source, language, edits = None))]
pub fn parse_with_edits<'py>(
    py: Python<'py>,
    source: &str,
    language: &str,
    edits: Option<Vec<InputEdit>>,
) -> PyResult<Bound<'py, PyAny>> {
    let edits_vec = edits.unwrap_or_default();

    // Release GIL during CPU-intensive parsing
    // NOTE: Currently always passes None for old_tree. For true incremental
    // parsing, maintain trees in memory via IncrementalParseContext.
    let result: ParseResult = py.detach(|| {
        parse_with_edits_internal(source, language, None, &edits_vec)
    });

    // Convert result to Python dict
    let json_str = serde_json::to_string(&result)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Serialization error: {}", e)))?;

    let json_module = py.import("json")?;
    let py_dict = json_module.call_method1("loads", (json_str,))?;
    Ok(py_dict)
}

/// Create an InputEdit for inserting text at a position.
///
/// # Arguments
/// * `position` - (line, column) tuple where insertion starts
/// * `text` - The text being inserted
/// * `source` - The original source code (to calculate byte offsets)
///
/// # Returns
/// InputEdit configured for a text insertion
pub fn create_insert_edit(position: (usize, usize), text: &str, source: &str) -> Option<InputEdit> {
    let byte_offset = position_to_byte_offset(position, source)?;
    let text_len = text.len();

    // For insertion, old_end equals start (no bytes replaced)
    let new_end_byte = byte_offset + text_len;
    let new_end_position = advance_position(position, text);

    Some(InputEdit {
        start_byte: byte_offset,
        old_end_byte: byte_offset,
        new_end_byte,
        start_position: position,
        old_end_position: position,
        new_end_position,
    })
}

/// Create an InputEdit for deleting text.
///
/// # Arguments
/// * `start_position` - (line, column) where deletion starts
/// * `end_position` - (line, column) where deletion ends
/// * `source` - The original source code (to calculate byte offsets)
///
/// # Returns
/// InputEdit configured for a text deletion
pub fn create_delete_edit(
    start_position: (usize, usize),
    end_position: (usize, usize),
    source: &str,
) -> Option<InputEdit> {
    let start_byte = position_to_byte_offset(start_position, source)?;
    let old_end_byte = position_to_byte_offset(end_position, source)?;

    // For deletion, new_end equals start (no new text)
    Some(InputEdit {
        start_byte,
        old_end_byte,
        new_end_byte: start_byte,
        start_position,
        old_end_position: end_position,
        new_end_position: start_position,
    })
}

/// Create an InputEdit for replacing text.
///
/// # Arguments
/// * `start_position` - (line, column) where replacement starts
/// * `end_position` - (line, column) where old text ends
/// * `new_text` - The replacement text
/// * `source` - The original source code
///
/// # Returns
/// InputEdit configured for text replacement
pub fn create_replace_edit(
    start_position: (usize, usize),
    end_position: (usize, usize),
    new_text: &str,
    source: &str,
) -> Option<InputEdit> {
    let start_byte = position_to_byte_offset(start_position, source)?;
    let old_end_byte = position_to_byte_offset(end_position, source)?;
    let new_end_byte = start_byte + new_text.len();
    let new_end_position = advance_position(start_position, new_text);

    Some(InputEdit {
        start_byte,
        old_end_byte,
        new_end_byte,
        start_position,
        old_end_position: end_position,
        new_end_position,
    })
}

/// Convert a line/column position to a byte offset.
fn position_to_byte_offset(position: (usize, usize), source: &str) -> Option<usize> {
    let (target_line, target_col) = position;
    let mut current_line = 0;
    let mut current_byte = 0;

    for line in source.lines() {
        if current_line == target_line {
            // Found the right line, check if column is valid
            let line_len = line.len();
            if target_col <= line_len {
                return Some(current_byte + target_col);
            } else {
                return None; // Column out of range
            }
        }
        // Move to next line (+1 for newline)
        current_byte += line.len() + 1;
        current_line += 1;
    }

    // Check if position is at end of file
    if target_line == current_line && target_col == 0 {
        Some(source.len())
    } else {
        None
    }
}

/// Advance a position by text (for calculating new end positions).
fn advance_position(start: (usize, usize), text: &str) -> (usize, usize) {
    let (mut line, mut col) = start;

    for ch in text.chars() {
        if ch == '\n' {
            line += 1;
            col = 0;
        } else {
            col += 1;
        }
    }

    (line, col)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_input_edit_creation() {
        let edit = InputEdit::new(
            10,
            15,
            20,
            (0, 10),
            (0, 15),
            (0, 20),
        );

        assert_eq!(edit.start_byte, 10);
        assert_eq!(edit.old_end_byte, 15);
        assert_eq!(edit.new_end_byte, 20);
        assert_eq!(edit.start_position, (0, 10));
        assert_eq!(edit.old_end_position, (0, 15));
        assert_eq!(edit.new_end_position, (0, 20));
    }

    #[test]
    fn test_input_edit_to_ts_edit() {
        let edit = InputEdit::new(
            10,
            15,
            20,
            (0, 10),
            (0, 15),
            (0, 20),
        );

        let ts_edit = edit.to_ts_edit();

        assert_eq!(ts_edit.start_byte, 10);
        assert_eq!(ts_edit.old_end_byte, 15);
        assert_eq!(ts_edit.new_end_byte, 20);
        assert_eq!(ts_edit.start_position.row, 0);
        assert_eq!(ts_edit.start_position.column, 10);
        assert_eq!(ts_edit.old_end_position.row, 0);
        assert_eq!(ts_edit.old_end_position.column, 15);
        assert_eq!(ts_edit.new_end_position.row, 0);
        assert_eq!(ts_edit.new_end_position.column, 20);
    }

    #[test]
    fn test_position_to_byte_offset() {
        let source = "line1\nline2\nline3";

        assert_eq!(position_to_byte_offset((0, 0), source), Some(0));   // Start
        assert_eq!(position_to_byte_offset((0, 5), source), Some(5));   // End of line1
        assert_eq!(position_to_byte_offset((1, 0), source), Some(6));  // Start of line2
        assert_eq!(position_to_byte_offset((1, 5), source), Some(11)); // End of line2
        assert_eq!(position_to_byte_offset((2, 0), source), Some(12));  // Start of line3
        assert_eq!(position_to_byte_offset((2, 5), source), Some(17));  // End of line3
    }

    #[test]
    fn test_advance_position() {
        assert_eq!(advance_position((0, 0), "hello"), (0, 5));
        assert_eq!(advance_position((0, 0), "hello\nworld"), (1, 5));
        assert_eq!(advance_position((1, 3), "test"), (1, 7));
        assert_eq!(advance_position((0, 0), ""), (0, 0));
    }

    #[test]
    fn test_create_insert_edit() {
        let source = "def test(): pass";
        let edit = create_insert_edit((0, 12), "new ", source).unwrap();

        // Insert "new " before "pass"
        assert_eq!(edit.start_byte, 12);
        assert_eq!(edit.old_end_byte, 12); // No deletion
        assert_eq!(edit.new_end_byte, 16); // 12 + 4 chars
        assert_eq!(edit.start_position, (0, 12));
        assert_eq!(edit.new_end_position, (0, 16));
    }

    #[test]
    fn test_create_delete_edit() {
        let source = "def test(): pass";
        // Delete "pass"
        let edit = create_delete_edit((0, 12), (0, 16), source).unwrap();

        assert_eq!(edit.start_byte, 12);
        assert_eq!(edit.old_end_byte, 16);
        assert_eq!(edit.new_end_byte, 12); // Same as start (deletion)
    }

    #[test]
    fn test_create_replace_edit() {
        let source = "def test(): pass";
        // Replace "pass" with "return 42"
        let edit = create_replace_edit((0, 12), (0, 16), "return 42", source).unwrap();

        assert_eq!(edit.start_byte, 12);
        assert_eq!(edit.old_end_byte, 16);
        assert_eq!(edit.new_end_byte, 21); // 12 + 9 chars
    }

    #[test]
    fn test_parse_with_edits_fresh_parse() {
        let source = "def hello(): pass";
        let result = parse_with_edits_internal(source, "python", None, &[]);

        assert!(result.success);
        assert!(result.tree.is_some());
        assert_eq!(result.language, "python");
    }

    #[test]
    fn test_parse_with_edits_incremental() {
        // First, do a full parse to get a tree
        let source = "def hello(): pass";
        let lang_name = "python";

        let ts_language = get_language(lang_name).unwrap();
        let mut parser = Parser::new();
        parser.set_language(&ts_language).unwrap();
        let old_tree = parser.parse(source, None).unwrap();

        // Now do an incremental parse with edits
        let new_source = "def hello(): return 42";
        let edit = InputEdit::new(
            12,  // start_byte
            16,  // old_end_byte ("pass")
            21,  // new_end_byte ("return 42")
            (0, 12),  // start_position
            (0, 16),  // old_end_position
            (0, 21),  // new_end_position
        );

        let result = parse_with_edits_internal(new_source, "python", Some(&old_tree), &[edit]);

        assert!(result.success);
        assert!(result.tree.is_some());
        assert_eq!(result.language, "python");
    }

    #[test]
    fn test_input_edit_equality() {
        let edit1 = InputEdit::new(10, 15, 20, (0, 10), (0, 15), (0, 20));
        let edit2 = InputEdit::new(10, 15, 20, (0, 10), (0, 15), (0, 20));
        let edit3 = InputEdit::new(10, 15, 21, (0, 10), (0, 15), (0, 20));

        assert_eq!(edit1, edit2);
        assert_ne!(edit1, edit3);
    }
}
