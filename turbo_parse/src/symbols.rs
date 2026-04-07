//! Symbol outline extraction using tree-sitter queries.
//!
//! Provides extraction of symbols (functions, classes, methods, imports)
//! from source code in Python, Rust, JavaScript, TypeScript, TSX, and Elixir.

use std::time::Instant;
use serde::{Deserialize, Serialize};
use streaming_iterator::StreamingIterator;
use tree_sitter::{Language, Node, Parser, Query, QueryCursor};

use crate::registry::{get_language, RegistryError};

/// Kind of symbol extracted from source code.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SymbolKind {
    /// Function definition
    Function,
    /// Class/struct definition
    Class,
    /// Method definition (function inside class)
    Method,
    /// Import statement
    Import,
    /// Variable/constant declaration
    Variable,
    /// Struct definition (Rust-specific)
    Struct,
    /// Interface definition (TypeScript-specific)
    Interface,
    /// Module definition
    Module,
    /// Trait definition (Rust-specific)
    Trait,
    /// Enum definition
    Enum,
    /// Type alias
    TypeAlias,
}

impl std::fmt::Display for SymbolKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            SymbolKind::Function => "function",
            SymbolKind::Class => "class",
            SymbolKind::Method => "method",
            SymbolKind::Import => "import",
            SymbolKind::Variable => "variable",
            SymbolKind::Struct => "struct",
            SymbolKind::Interface => "interface",
            SymbolKind::Module => "module",
            SymbolKind::Trait => "trait",
            SymbolKind::Enum => "enum",
            SymbolKind::TypeAlias => "type_alias",
        };
        write!(f, "{}", s)
    }
}

/// A single symbol extracted from source code.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Symbol {
    /// Name of the symbol
    pub name: String,
    /// Kind of symbol
    pub kind: SymbolKind,
    /// Start line (1-indexed)
    pub start_line: usize,
    /// End line (1-indexed)
    pub end_line: usize,
    /// Start column (0-indexed)
    pub start_col: usize,
    /// End column (0-indexed)
    pub end_col: usize,
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
        kind: SymbolKind,
        start_line: usize,
        end_line: usize,
        start_col: usize,
        end_col: usize,
    ) -> Self {
        Self {
            name: name.into(),
            kind,
            start_line,
            end_line,
            start_col,
            end_col,
            parent: None,
            docstring: None,
        }
    }

    /// Set the parent symbol.
    pub fn with_parent(mut self, parent: impl Into<String>) -> Self {
        self.parent = Some(parent.into());
        self
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
    pub fn symbols_of_kind(&self, kind: SymbolKind) -> Vec<&Symbol> {
        self.symbols.iter().filter(|s| s.kind == kind).collect()
    }

    /// Get top-level symbols (those without a parent).
    pub fn top_level_symbols(&self) -> Vec<&Symbol> {
        self.symbols.iter().filter(|s| s.parent.is_none()).collect()
    }
}

/// Tree-sitter queries for symbol extraction.
mod queries {
    /// Query for Python symbol extraction.
    pub const PYTHON: &str = r#"
        ; Function definitions
        (function_definition
          name: (identifier) @name) @function

        ; Class definitions
        (class_definition
          name: (identifier) @name) @class

        ; Method definitions inside classes
        (class_definition
          body: (block
            (function_definition
              name: (identifier) @name) @method))

        ; Import statements - simple import
        (import_statement
          name: (dotted_name) @name) @import

        ; Import from statements
        (import_from_statement
          module_name: (dotted_name) @name) @import

        ; Import from with imported names
        (import_from_statement
          (dotted_name (identifier) @name)) @import
    "#;

    /// Query for Rust symbol extraction.
    pub const RUST: &str = r#"
        ; Function items
        (function_item
          name: (identifier) @name) @function

        ; Struct items
        (struct_item
          name: (type_identifier) @name) @struct

        ; Impl items (with methods inside)
        (impl_item
          type: (type_identifier) @name
          body: (declaration_list
            (function_item
              name: (identifier) @method_name) @method))

        ; Use declarations
        (use_declaration
          argument: (identifier) @name) @import

        (use_declaration
          argument: (scoped_identifier) @name) @import

        ; Trait definitions
        (trait_item
          name: (type_identifier) @name) @trait

        ; Enum definitions
        (enum_item
          name: (type_identifier) @name) @enum

        ; Type aliases
        (type_item
          name: (type_identifier) @name) @type_alias

        ; Module definitions
        (mod_item
          name: (identifier) @name) @module

        ; Constant definitions
        (const_item
          name: (identifier) @name) @variable
    "#;

    /// Query for JavaScript/TypeScript symbol extraction.
    pub const JAVASCRIPT: &str = r#"
        ; Function declarations
        (function_declaration
          name: (identifier) @name) @function

        ; Function expressions in variable declarations
        (lexical_declaration
          (variable_declarator
            name: (identifier) @name
            value: (function_expression))) @function

        ; Arrow functions in variable declarations
        (lexical_declaration
          (variable_declarator
            name: (identifier) @name
            value: (arrow_function))) @function

        ; Class declarations
        (class_declaration
          name: (identifier) @name) @class

        ; Method definitions
        (method_definition
          name: (property_identifier) @name) @method

        ; Import statements
        (import_statement
          (import_clause
            (identifier) @name)) @import

        ; Named imports
        (import_statement
          (import_clause
            (named_imports
              (import_specifier
                name: (identifier) @name)))) @import

        ; Variable declarations at module level
        (program
          (lexical_declaration
            (variable_declarator
              name: (identifier) @name))) @variable
    "#;

    /// Query for TypeScript (extends JavaScript with interface support).
    pub const TYPESCRIPT: &str = r#"
        ; Function declarations
        (function_declaration
          name: (identifier) @name) @function

        ; Function expressions in variable declarations
        (lexical_declaration
          (variable_declarator
            name: (identifier) @name
            value: (function_expression))) @function

        ; Arrow functions in variable declarations
        (lexical_declaration
          (variable_declarator
            name: (identifier) @name
            value: (arrow_function))) @function

        ; Class declarations (TypeScript uses same grammar as JavaScript)
        (class_declaration
          name: (type_identifier) @name) @class

        ; Method definitions
        (method_definition
          name: (property_identifier) @name) @method

        ; Import statements
        (import_statement
          (import_clause
            (identifier) @name)) @import

        ; Named imports
        (import_statement
          (import_clause
            (named_imports
              (import_specifier
                name: (identifier) @name)))) @import

        ; Variable declarations at module level
        (program
          (lexical_declaration
            (variable_declarator
              name: (identifier) @name))) @variable

        ; TypeScript-specific: Interface declarations
        (interface_declaration
          name: (type_identifier) @name) @interface

        ; Type aliases
        (type_alias_declaration
          name: (type_identifier) @name) @type_alias

        ; Enum declarations
        (enum_declaration
          name: (identifier) @name) @enum
    "#;

    /// Query for TSX (TypeScript with JSX - same as TypeScript).
    pub const TSX: &str = TYPESCRIPT;

    /// Query for Elixir symbol extraction.
    pub const ELIXIR: &str = r#"
        ; Function definitions
        (call
          target: (identifier) @def_keyword
          (arguments
            (identifier) @name)
          (do_block)
          (#any-of? @def_keyword "def" "defp" "defmacro" "defmacrop")) @function

        ; Module definitions
        (call
          target: (identifier) @module_keyword
          (arguments
            (alias) @name)
          (do_block)
          (#eq? @module_keyword "defmodule")) @module

        ; Import/use/require statements
        (call
          target: (identifier) @import_keyword
          (arguments
            (alias) @name)
          (#any-of? @import_keyword "import" "use" "require")) @import

        ; Alias statements
        (call
          target: (identifier) @alias_keyword
          (arguments
            (alias) @name)
          (#eq? @alias_keyword "alias")) @import
    "#;
}

/// Normalize language name and return owned String.
pub fn normalize_language(name: &str) -> String {
    match name.to_lowercase().as_str() {
        "py" => "python".to_string(),
        "js" => "javascript".to_string(),
        "ts" => "typescript".to_string(),
        "ex" | "exs" => "elixir".to_string(),
        other => other.to_string(),
    }
}

/// Get the query string for a language.
fn get_query_for_language(language: &str) -> Option<&'static str> {
    match normalize_language(language).as_str() {
        "python" => Some(queries::PYTHON),
        "rust" => Some(queries::RUST),
        "javascript" => Some(queries::JAVASCRIPT),
        "typescript" => Some(queries::TYPESCRIPT),
        "tsx" => Some(queries::TSX),
        "elixir" => Some(queries::ELIXIR),
        _ => None,
    }
}

/// Extract a node name from a capture.
fn extract_node_name(node: Node, source: &str) -> Option<String> {
    let text = node.utf8_text(source.as_bytes()).ok()?;
    Some(text.to_string())
}

fn execute_symbol_query(
    _language: &Language,
    query: &Query,
    tree: &tree_sitter::Tree,
    source: &str,
    lang_name: &str,
) -> Vec<Symbol> {
    let mut symbols: Vec<(Symbol, Node<'_>)> = Vec::new();

    // Execute the query
    let mut cursor = QueryCursor::new();
    let mut matches = cursor.matches(query, tree.root_node(), source.as_bytes());

    while let Some(m) = matches.next() {
        // Find the pattern capture (for kind) and name capture
        let mut kind_node: Option<Node> = None;
        let mut kind_capture: Option<&str> = None;
        let mut name_node: Option<Node> = None;

        for capture in m.captures {
            let node = capture.node;
            let capture_name = &query.capture_names()[capture.index as usize];

            // Check if this is a pattern kind capture
            let is_kind_capture = matches!(
                *capture_name,
                "function" | "class" | "method" | "import" | "variable" |
                "struct" | "interface" | "module" | "trait" | "enum" | "type_alias"
            );

            if is_kind_capture {
                kind_node = Some(node);
                kind_capture = Some(capture_name);
            } else if *capture_name == "name" || *capture_name == "method_name" {
                name_node = Some(node);
            }
        }

        // If we have both a kind and a name, create a symbol
        if let (Some(kind), Some(name_node)) = (kind_capture, name_node) {
            if let Some(name) = extract_node_name(name_node, source) {
                let start_pos = name_node.start_position();
                let end_pos = name_node.end_position();

                let start_line = start_pos.row + 1; // 1-indexed
                let end_line = end_pos.row + 1;
                let start_col = start_pos.column;
                let end_col = end_pos.column;

                let symbol_kind = kind_from_capture(kind);

                // Check for duplicates
                let exists = symbols.iter().any(|(s, _)| {
                    s.name == name && s.start_line == start_line && s.start_col == start_col
                });

                if !exists {
                    symbols.push((
                        Symbol::new(
                            name,
                            symbol_kind,
                            start_line,
                            end_line,
                            start_col,
                            end_col,
                        ),
                        kind_node.unwrap_or(name_node),
                    ));
                }
            }
        }
    }

    // Second pass: set parent relationships for methods
    let mut result: Vec<Symbol> = Vec::new();
    for (symbol, _kind_node) in symbols {
        let symbol = if symbol.kind == SymbolKind::Function || symbol.kind == SymbolKind::Method {
            // Check if this function is inside a class
            if let Some(parent_name) = find_method_parent(lang_name, &symbol, source, tree) {
                symbol.with_parent(parent_name)
            } else {
                symbol
            }
        } else {
            symbol
        };
        result.push(symbol);
    }

    // Sort by position
    result.sort_by(|a, b| {
        a.start_line
            .cmp(&b.start_line)
            .then(a.start_col.cmp(&b.start_col))
    });

    result
}

/// Map capture name to SymbolKind.
fn kind_from_capture(capture_name: &str) -> SymbolKind {
    match capture_name {
        "function" => SymbolKind::Function,
        "class" => SymbolKind::Class,
        "method" => SymbolKind::Method,
        "import" => SymbolKind::Import,
        "variable" => SymbolKind::Variable,
        "struct" => SymbolKind::Struct,
        "interface" => SymbolKind::Interface,
        "module" => SymbolKind::Module,
        "trait" => SymbolKind::Trait,
        "enum" => SymbolKind::Enum,
        "type_alias" => SymbolKind::TypeAlias,
        _ => SymbolKind::Variable,
    }
}

/// Build a query for the given language.
fn build_query(language: &Language, query_str: &str) -> Result<Query, String> {
    Query::new(language, query_str).map_err(|e| format!("Query error: {:?}", e))
}



/// Find parent for a method.
fn find_method_parent(
    lang_name: &str,
    symbol: &Symbol,
    source: &str,
    tree: &tree_sitter::Tree,
) -> Option<String> {
    let root = tree.root_node();

    // Find the node at this position
    let target_byte = find_byte_offset(source, symbol.start_line - 1, symbol.start_col);
    let node_at_pos = root.descendant_for_byte_range(target_byte, target_byte)?;

    // Walk up to find parent class/impl
    let mut current = node_at_pos.parent();
    while let Some(parent) = current {
        let kind = parent.kind();

        match lang_name {
            "python" => {
                if kind == "class_definition" {
                    // Find the class name
                    for i in 0..parent.child_count() {
                        if let Some(child) = parent.child(i) {
                            if child.kind() == "identifier" {
                                return extract_node_name(child, source);
                            }
                        }
                    }
                }
            }
            "rust" => {
                if kind == "impl_item" {
                    // Find the type name
                    for i in 0..parent.child_count() {
                        if let Some(child) = parent.child(i) {
                            if child.kind() == "type_identifier" {
                                return extract_node_name(child, source);
                            }
                        }
                    }
                }
            }
            "javascript" | "typescript" | "tsx" => {
                if kind == "class_declaration" || kind == "class_body" {
                    // Walk further up to find the class declaration
                    if kind == "class_body" {
                        if let Some(class_decl) = parent.parent() {
                            if class_decl.kind() == "class_declaration" {
                                for i in 0..class_decl.child_count() {
                                    if let Some(child) = class_decl.child(i) {
                                        if child.kind() == "identifier" {
                                            return extract_node_name(child, source);
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            _ => {}
        }

        current = parent.parent();
    }

    None
}

/// Find byte offset for a position.
fn find_byte_offset(source: &str, row: usize, col: usize) -> usize {
    let lines: Vec<&str> = source.lines().collect();
    let mut offset = 0;

    for (i, line) in lines.iter().enumerate() {
        if i == row {
            return offset + col.min(line.len());
        }
        offset += line.len() + 1; // +1 for newline
    }

    offset
}


/// Extract symbols from source code.
///
/// # Arguments
/// * `source` - The source code to analyze
/// * `language` - The language identifier (e.g., "python", "rust")
///
/// # Returns
/// A `SymbolOutline` containing all extracted symbols.
pub fn extract_symbols(source: &str, language: &str) -> SymbolOutline {
    let lang_name = normalize_language(language);
    let start = Instant::now();

    // Get the language
    let ts_language = match get_language(&lang_name) {
        Ok(lang) => lang,
        Err(RegistryError::UnsupportedLanguage(_)) => {
            return SymbolOutline::error(
                lang_name,
                format!("Unsupported language: '{}'", language),
            );
        }
        Err(e) => {
            return SymbolOutline::error(
                lang_name,
                format!("Language initialization error: {}", e),
            );
        }
    };

    // Get query for this language
    let query_str = match get_query_for_language(&lang_name) {
        Some(q) => q,
        None => {
            return SymbolOutline::error(
                lang_name,
                format!("No symbol query available for language: '{}'", language),
            );
        }
    };

    // Parse the source
    let mut parser = Parser::new();
    if let Err(e) = parser.set_language(ts_language) {
        return SymbolOutline::error(
            lang_name,
            format!("Failed to set language: {}", e),
        );
    }

    let tree = match parser.parse(source, None) {
        Some(t) => t,
        None => {
            return SymbolOutline::error(
                lang_name,
                "Parser returned no tree",
            );
        }
    };

    // Build and execute query
    let query = match build_query(ts_language, query_str) {
        Ok(q) => q,
        Err(e) => {
            return SymbolOutline::error(lang_name, e);
        }
    };

    let symbols = execute_symbol_query(ts_language, &query, &tree, source, &lang_name);
    let extraction_time_ms = start.elapsed().as_secs_f64() * 1000.0;

    SymbolOutline::new(lang_name, symbols, extraction_time_ms, true)
}

/// Extract symbols from a file.
///
/// # Arguments
/// * `path` - Path to the file
/// * `language` - Optional language override (detected from extension if not provided)
///
/// # Returns
/// A `SymbolOutline` containing all extracted symbols.
pub fn extract_symbols_from_file(
    path: &str,
    language: Option<&str>,
) -> SymbolOutline {
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
                    return SymbolOutline::error(
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
            return SymbolOutline::error(
                &lang,
                format!("Failed to read file '{}': {}", path, e),
            );
        }
    };

    extract_symbols(&source, &lang)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_symbol_kind_display() {
        assert_eq!(format!("{}", SymbolKind::Function), "function");
        assert_eq!(format!("{}", SymbolKind::Class), "class");
        assert_eq!(format!("{}", SymbolKind::Method), "method");
        assert_eq!(format!("{}", SymbolKind::Import), "import");
    }

    #[test]
    fn test_symbol_new() {
        let sym = Symbol::new("test", SymbolKind::Function, 1, 10, 0, 5);
        assert_eq!(sym.name, "test");
        assert_eq!(sym.kind, SymbolKind::Function);
        assert_eq!(sym.start_line, 1);
        assert_eq!(sym.end_line, 10);
        assert_eq!(sym.start_col, 0);
        assert_eq!(sym.end_col, 5);
        assert!(sym.parent.is_none());
    }

    #[test]
    fn test_symbol_with_parent() {
        let sym = Symbol::new("method", SymbolKind::Method, 2, 5, 4, 15)
            .with_parent("MyClass");
        assert_eq!(sym.parent, Some("MyClass".to_string()));
    }

    #[test]
    fn test_symbol_outline_new() {
        let symbols = vec![
            Symbol::new("func1", SymbolKind::Function, 1, 5, 0, 10),
            Symbol::new("Class1", SymbolKind::Class, 7, 15, 0, 20),
        ];
        let outline = SymbolOutline::new("python", symbols, 0.5, true);
        
        assert_eq!(outline.language, "python");
        assert_eq!(outline.symbols.len(), 2);
        assert!(outline.success);
        assert!(outline.errors.is_empty());
    }

    #[test]
    fn test_symbol_outline_error() {
        let outline = SymbolOutline::error("python", "test error");
        
        assert_eq!(outline.language, "python");
        assert!(!outline.success);
        assert_eq!(outline.errors.len(), 1);
        assert_eq!(outline.errors[0], "test error");
    }

    #[test]
    fn test_symbol_outline_filtering() {
        let symbols = vec![
            Symbol::new("func1", SymbolKind::Function, 1, 5, 0, 10),
            Symbol::new("Class1", SymbolKind::Class, 7, 15, 0, 20),
            Symbol::new("method1", SymbolKind::Method, 8, 10, 4, 15).with_parent("Class1"),
        ];
        let outline = SymbolOutline::new("python", symbols, 0.5, true);
        
        let functions = outline.symbols_of_kind(SymbolKind::Function);
        assert_eq!(functions.len(), 1);
        assert_eq!(functions[0].name, "func1");
        
        let classes = outline.symbols_of_kind(SymbolKind::Class);
        assert_eq!(classes.len(), 1);
        assert_eq!(classes[0].name, "Class1");
        
        let top_level = outline.top_level_symbols();
        assert_eq!(top_level.len(), 2); // func1 and Class1 (method1 has parent)
    }

    #[test]
    fn test_extract_symbols_python_simple() {
        let source = r#"def hello():
    pass
"#;
        let outline = extract_symbols(source, "python");
        
        assert!(outline.success);
        assert_eq!(outline.language, "python");
        assert!(outline.symbols.iter().any(|s| s.name == "hello" && s.kind == SymbolKind::Function));
    }

    #[test]
    fn test_extract_symbols_python_class() {
        let source = r#"class MyClass:
    def method(self):
        pass
"#;
        let outline = extract_symbols(source, "python");
        
        assert!(outline.success);
        assert!(outline.symbols.iter().any(|s| s.name == "MyClass" && s.kind == SymbolKind::Class));
        assert!(outline.symbols.iter().any(|s| {
            s.name == "method"
                && s.kind == SymbolKind::Method
                && s.parent.as_ref() == Some(&"MyClass".to_string())
        }));
    }

    #[test]
    fn test_extract_symbols_rust() {
        let source = r#"fn main() {
    println!("Hello");
}

struct Point {
    x: i32,
    y: i32,
}
"#;
        let outline = extract_symbols(source, "rust");
        
        assert!(outline.success);
        assert!(outline.symbols.iter().any(|s| s.name == "main" && s.kind == SymbolKind::Function));
        assert!(outline.symbols.iter().any(|s| s.name == "Point" && s.kind == SymbolKind::Struct));
    }

    #[test]
    fn test_extract_symbols_javascript() {
        let source = r#"function greet() {
    return "Hello";
}

class MyClass {
    doSomething() {}
}
"#;
        let outline = extract_symbols(source, "javascript");
        
        assert!(outline.success);
        assert!(outline.symbols.iter().any(|s| s.name == "greet" && s.kind == SymbolKind::Function));
        assert!(outline.symbols.iter().any(|s| s.name == "MyClass" && s.kind == SymbolKind::Class));
    }

    #[test]
    fn test_extract_symbols_typescript() {
        let source = r#"interface User {
    name: string;
}

function getUser(): User {
    return { name: "test" };
}
"#;
        let outline = extract_symbols(source, "typescript");
        
        assert!(outline.success);
        assert!(outline.symbols.iter().any(|s| s.name == "User" && s.kind == SymbolKind::Interface));
        assert!(outline.symbols.iter().any(|s| s.name == "getUser" && s.kind == SymbolKind::Function));
    }

    #[test]
    fn test_extract_symbols_elixir() {
        let source = r#"defmodule MyModule do
    def hello do
        :world
    end
end
"#;
        let outline = extract_symbols(source, "elixir");
        
        assert!(outline.success);
        assert!(outline.symbols.iter().any(|s| s.name == "MyModule" && s.kind == SymbolKind::Module));
        assert!(outline.symbols.iter().any(|s| s.name == "hello" && s.kind == SymbolKind::Function));
    }

    #[test]
    fn test_extract_symbols_unsupported() {
        let source = "some code";
        let outline = extract_symbols(source, "unsupported");
        
        assert!(!outline.success);
        assert!(!outline.errors.is_empty());
    }

    #[test]
    fn test_extract_symbols_imports_python() {
        let source = r#"import os
from typing import List

def test():
    pass
"#;
        let outline = extract_symbols(source, "python");
        
        assert!(outline.success);
        let imports = outline.symbols_of_kind(SymbolKind::Import);
        assert!(!imports.is_empty());
    }

    #[test]
    fn test_normalize_language() {
        assert_eq!(normalize_language("py"), "python");
        assert_eq!(normalize_language("python"), "python");
        assert_eq!(normalize_language("js"), "javascript");
        assert_eq!(normalize_language("ts"), "typescript");
        assert_eq!(normalize_language("ex"), "elixir");
        assert_eq!(normalize_language("exs"), "elixir");
        assert_eq!(normalize_language("rust"), "rust");
    }
}
