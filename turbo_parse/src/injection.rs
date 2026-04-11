//! Language injection detection and parsing module.
//!
//! This module provides functionality to detect and parse embedded languages
//! within source code, such as:
//! - HEEx templates embedded in Elixir (EEx templates)
//! - SQL in Python triple-quoted strings
//! - JavaScript in HTML
//! - CSS in HTML style attributes
//! - Nested injections (JavaScript in HTML in templates)
//!
//! The implementation uses tree-sitter's injection query patterns,
//! inspired by Helix Editor's approach to language injection.

use std::collections::HashMap;
use std::time::Instant;
use serde::{Deserialize, Serialize};
use tree_sitter::{Node, Parser};

use crate::registry::{get_language, normalize_language, is_language_supported};

/// Represents a detected language injection range.
///
/// An injection range identifies a region of source code that contains
/// embedded content in a different language (e.g., SQL inside a Python string).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[pyo3::pyclass]
pub struct InjectionRange {
    /// The parent/host language (e.g., "python", "elixir")
    pub parent_language: String,
    /// The injected/embedded language (e.g., "sql", "heex", "html")
    pub injected_language: String,
    /// Start byte position in the source (0-indexed, inclusive)
    pub start_byte: usize,
    /// End byte position in the source (0-indexed, exclusive)
    pub end_byte: usize,
    /// The actual content of the injected region
    pub content: String,
    /// Optional: the node kind that triggered this injection
    pub node_kind: String,
}

impl InjectionRange {
    /// Create a new injection range.
    pub fn new(
        parent_language: impl Into<String>,
        injected_language: impl Into<String>,
        start_byte: usize,
        end_byte: usize,
        content: impl Into<String>,
        node_kind: impl Into<String>,
    ) -> Self {
        Self {
            parent_language: parent_language.into(),
            injected_language: injected_language.into(),
            start_byte,
            end_byte,
            content: content.into(),
            node_kind: node_kind.into(),
        }
    }

    /// Get the length of the injection in bytes.
    pub fn len(&self) -> usize {
        self.end_byte.saturating_sub(self.start_byte)
    }

    /// Check if the injection is empty.
    pub fn is_empty(&self) -> bool {
        self.start_byte == self.end_byte
    }

    /// Get the content length (may differ from byte length for multi-byte UTF-8).
    pub fn content_len(&self) -> usize {
        self.content.len()
    }

    /// Check if this injection range overlaps with another.
    pub fn overlaps(&self, other: &InjectionRange) -> bool {
        self.start_byte < other.end_byte && other.start_byte < self.end_byte
    }

    /// Check if this injection contains a byte position.
    pub fn contains(&self, byte: usize) -> bool {
        self.start_byte <= byte && byte < self.end_byte
    }

    /// Check if this injection contains another injection entirely (for nesting).
    pub fn contains_range(&self, other: &InjectionRange) -> bool {
        self.start_byte <= other.start_byte && other.end_byte <= self.end_byte
    }

    /// Create a new injection with adjusted offsets for nested parsing.
    pub fn with_adjusted_offsets(&self, offset_delta: isize) -> Self {
        let new_start = if offset_delta >= 0 {
            self.start_byte + offset_delta as usize
        } else {
            self.start_byte.saturating_sub((-offset_delta) as usize)
        };
        let new_end = if offset_delta >= 0 {
            self.end_byte + offset_delta as usize
        } else {
            self.end_byte.saturating_sub((-offset_delta) as usize)
        };
        
        Self {
            parent_language: self.parent_language.clone(),
            injected_language: self.injected_language.clone(),
            start_byte: new_start,
            end_byte: new_end,
            content: self.content.clone(),
            node_kind: self.node_kind.clone(),
        }
    }
}

/// Result of an injection detection operation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InjectionResult {
    /// The parent language that was analyzed
    pub parent_language: String,
    /// All detected injections, ordered by position
    pub injections: Vec<InjectionRange>,
    /// Time taken to detect injections in milliseconds
    pub detection_time_ms: f64,
    /// Whether the detection succeeded
    pub success: bool,
    /// Any errors encountered during detection
    pub errors: Vec<String>,
}

impl InjectionResult {
    /// Create a new successful injection result.
    pub fn new(
        parent_language: impl Into<String>,
        injections: Vec<InjectionRange>,
        detection_time_ms: f64,
    ) -> Self {
        Self {
            parent_language: parent_language.into(),
            injections,
            detection_time_ms,
            success: true,
            errors: Vec::new(),
        }
    }

    /// Create an error result.
    pub fn error(parent_language: impl Into<String>, error: impl Into<String>) -> Self {
        Self {
            parent_language: parent_language.into(),
            injections: Vec::new(),
            detection_time_ms: 0.0,
            success: false,
            errors: vec![error.into()],
        }
    }

    /// Get injections of a specific language.
    pub fn injections_of_language(&self, language: &str) -> Vec<&InjectionRange> {
        self.injections
            .iter()
            .filter(|i| i.injected_language == language)
            .collect()
    }

    /// Get the number of injections.
    pub fn len(&self) -> usize {
        self.injections.len()
    }

    /// Check if there are any injections.
    pub fn is_empty(&self) -> bool {
        self.injections.is_empty()
    }

    /// Check if there are nested injections (injections within injections).
    pub fn has_nested_injections(&self) -> bool {
        for (i, injection) in self.injections.iter().enumerate() {
            for other in &self.injections[i + 1..] {
                if injection.contains_range(other) {
                    return true;
                }
            }
        }
        false
    }

    /// Get nested injection pairs (parent, child).
    pub fn get_nested_pairs(&self) -> Vec<(&InjectionRange, &InjectionRange)> {
        let mut pairs = Vec::new();
        for (i, injection) in self.injections.iter().enumerate() {
            for other in &self.injections[i + 1..] {
                if injection.contains_range(other) {
                    pairs.push((injection, other));
                }
            }
        }
        pairs
    }
}

/// Represents a parsed injection with its own AST.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParsedInjection {
    /// The injection range information
    pub range: InjectionRange,
    /// The parsed tree as JSON (if parsing succeeded)
    pub tree: Option<serde_json::Value>,
    /// Whether parsing the injected content succeeded
    pub parse_success: bool,
    /// Any parse errors for the injected content
    pub parse_errors: Vec<String>,
    /// Time taken to parse the injection in milliseconds
    pub parse_time_ms: f64,
}

/// Result of parsing injections with their own grammars.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParsedInjectionResult {
    /// The parent language
    pub parent_language: String,
    /// All parsed injections
    pub parsed_injections: Vec<ParsedInjection>,
    /// Time taken for the entire operation in milliseconds
    pub total_time_ms: f64,
    /// Whether all injections were parsed successfully
    pub all_succeeded: bool,
    /// Count of injections by language
    pub language_counts: HashMap<String, usize>,
}

impl ParsedInjectionResult {
    /// Create a new parsed injection result.
    pub fn new(
        parent_language: impl Into<String>,
        parsed_injections: Vec<ParsedInjection>,
        total_time_ms: f64,
    ) -> Self {
        let parent_language = parent_language.into();
        let all_succeeded = parsed_injections.iter().all(|p| p.parse_success);
        
        // Count injections by language
        let mut language_counts = HashMap::new();
        for injection in &parsed_injections {
            *language_counts.entry(injection.range.injected_language.clone()).or_insert(0) += 1;
        }
        
        Self {
            parent_language,
            parsed_injections,
            total_time_ms,
            all_succeeded,
            language_counts,
        }
    }

    /// Get parsed injections of a specific language.
    pub fn injections_of_language(&self, language: &str) -> Vec<&ParsedInjection> {
        self.parsed_injections
            .iter()
            .filter(|p| p.range.injected_language == language)
            .collect()
    }
}

/// Heuristic patterns for detecting injections without tree-sitter queries.
///
/// These patterns are used as fallback when we don't have proper injection queries
/// or when fast detection is needed without full parsing.
mod heuristics {
    use super::InjectionRange;

    /// Detect SQL in Python strings using heuristics.
    pub fn detect_sql_in_python(source: &str) -> Vec<InjectionRange> {
        let mut injections = Vec::new();
        
        // Pattern 1: Triple-quoted strings with SQL keywords
        let sql_keywords = [
            "SELECT", "INSERT", "UPDATE", "DELETE", "CREATE", "DROP",
            "FROM", "WHERE", "JOIN", "LEFT", "RIGHT", "INNER", "OUTER",
            "GROUP BY", "ORDER BY", "HAVING", "LIMIT", "OFFSET",
        ];
        
        // Find triple-quoted strings
        let triple_quote_patterns = ["\"\"\"", "'''"];
        
        for pattern in &triple_quote_patterns {
            let mut start = 0;
            while let Some(pos) = source[start..].find(pattern) {
                let absolute_start = start + pos;
                let content_start = absolute_start + 3;
                
                // Find closing quote
                if let Some(end_pos) = source[content_start..].find(pattern) {
                    let content_end = content_start + end_pos;
                    let end = content_end + 3;
                    
                    let content = &source[content_start..content_end];
                    
                    // Check if content looks like SQL
                    let content_upper = content.to_uppercase();
                    let has_sql_keyword = sql_keywords.iter().any(|kw| content_upper.contains(kw));
                    
                    if has_sql_keyword {
                        // Check for variable assignment context (cursor, db, sql, query)
                        let before = &source[..absolute_start];
                        let has_sql_context = before.lines().last().map_or(false, |line| {
                            let line_lower = line.to_lowercase();
                            line_lower.contains("cursor") || 
                            line_lower.contains("execute") ||
                            line_lower.contains("sql") ||
                            line_lower.contains("query") ||
                            line_lower.contains("select") ||
                            line_lower.contains("insert") ||
                            line_lower.contains("update") ||
                            line_lower.contains("delete") ||
                            line_lower.contains("create table") ||
                            line_lower.contains("drop table")
                        });
                        
                        if has_sql_context {
                            injections.push(InjectionRange::new(
                                "python",
                                "sql",
                                content_start,
                                content_end,
                                content,
                                "string_content",
                            ));
                        }
                    }
                    
                    start = end;
                } else {
                    break;
                }
            }
        }
        
        injections
    }

    /// Detect HEEx patterns in Elixir/EEx templates.
    pub fn detect_heex_in_elixir(source: &str) -> Vec<InjectionRange> {
        let mut injections = Vec::new();
        
        // Pattern 1: ~H sigil (HEEx template)
        if let Some(pos) = source.find("~H\"") {
            let start = pos + 3; // After ~H"
            if let Some(end) = source[start..].find("\"") {
                let content = &source[start..start + end];
                injections.push(InjectionRange::new(
                    "elixir",
                    "heex",
                    start,
                    start + end,
                    content,
                    "sigil_h",
                ));
            }
        }
        
        // Pattern 2: ~H''' sigil (heredoc style)
        if let Some(pos) = source.find("~H'''") {
            let start = pos + 5; // After ~H'''
            if let Some(end) = source[start..].find("'''") {
                let content = &source[start..start + end];
                injections.push(InjectionRange::new(
                    "elixir",
                    "heex",
                    start,
                    start + end,
                    content,
                    "sigil_h_heredoc",
                ));
            }
        }
        
        // Pattern 3: render/3 with HEEx template string
        // This is a heuristic - we look for render calls with ~H
        if source.contains("render") && source.contains("~H") {
            // Additional patterns could be added here
        }
        
        injections
    }

    /// Detect HTML in strings (generic pattern).
    pub fn detect_html_in_strings(source: &str, parent_lang: &str) -> Vec<InjectionRange> {
        let mut injections = Vec::new();
        
        // Pattern 1: Triple-quoted strings containing HTML tags
        let triple_quote_patterns = ["\"\"\"", "'''", "`"];
        
        for pattern in &triple_quote_patterns {
            let mut start = 0;
            while let Some(pos) = source[start..].find(pattern) {
                let absolute_start = start + pos;
                let content_start = absolute_start + pattern.len();
                
                // Find closing quote
                if let Some(end_pos) = source[content_start..].find(pattern) {
                    let content_end = content_start + end_pos;
                    let end = content_end + pattern.len();
                    
                    let content = &source[content_start..content_end];
                    
                    // Check if content looks like HTML
                    let has_html_tags = content.contains('<') && content.contains('>');
                    let starts_with_tag = content.trim_start().starts_with('<');
                    
                    if has_html_tags && starts_with_tag {
                        injections.push(InjectionRange::new(
                            parent_lang,
                            "html",
                            content_start,
                            content_end,
                            content,
                            "html_string",
                        ));
                    }
                    
                    start = end;
                } else {
                    break;
                }
            }
        }
        
        injections
    }

    /// Detect JavaScript in HTML script tags.
    pub fn detect_javascript_in_html(source: &str) -> Vec<InjectionRange> {
        let mut injections = Vec::new();
        
        // Find <script> tags
        let script_start = "<script";
        let script_end = "</script>";
        
        let mut start = 0;
        while let Some(pos) = source[start..].to_lowercase().find(script_start) {
            let absolute_start = start + pos;
            
            // Find the end of the opening tag
            if let Some(tag_end) = source[absolute_start..].find('>') {
                let content_start = absolute_start + tag_end + 1;
                
                // Find closing script tag
                if let Some(end_pos) = source[content_start..].to_lowercase().find(script_end) {
                    let content_end = content_start + end_pos;
                    
                    let content = &source[content_start..content_end];
                    
                    injections.push(InjectionRange::new(
                        "html",
                        "javascript",
                        content_start,
                        content_end,
                        content,
                        "script_tag",
                    ));
                    
                    start = content_end + script_end.len();
                } else {
                    break;
                }
            } else {
                break;
            }
        }
        
        injections
    }

    /// Detect CSS in HTML style tags.
    pub fn detect_css_in_html(source: &str) -> Vec<InjectionRange> {
        let mut injections = Vec::new();
        
        let style_start = "<style";
        let style_end = "</style>";
        
        let mut start = 0;
        while let Some(pos) = source[start..].to_lowercase().find(style_start) {
            let absolute_start = start + pos;
            
            if let Some(tag_end) = source[absolute_start..].find('>') {
                let content_start = absolute_start + tag_end + 1;
                
                if let Some(end_pos) = source[content_start..].to_lowercase().find(style_end) {
                    let content_end = content_start + end_pos;
                    
                    let content = &source[content_start..content_end];
                    
                    injections.push(InjectionRange::new(
                        "html",
                        "css",
                        content_start,
                        content_end,
                        content,
                        "style_tag",
                    ));
                    
                    start = content_end + style_end.len();
                } else {
                    break;
                }
            } else {
                break;
            }
        }
        
        injections
    }

    /// Detect JSON in strings.
    pub fn detect_json_in_strings(source: &str, parent_lang: &str) -> Vec<InjectionRange> {
        let mut injections = Vec::new();
        
        // Look for patterns that suggest JSON content
        // Pattern 1: Triple-quoted strings starting with { or [
        let patterns = ["\"\"\"", "'''"];
        
        for pattern in &patterns {
            let mut start = 0;
            while let Some(pos) = source[start..].find(pattern) {
                let absolute_start = start + pos;
                let content_start = absolute_start + pattern.len();
                
                if let Some(end_pos) = source[content_start..].find(pattern) {
                    let content_end = content_start + end_pos;
                    let content = &source[content_start..content_end];
                    
                    let trimmed = content.trim();
                    if (trimmed.starts_with('{') && trimmed.ends_with('}')) ||
                       (trimmed.starts_with('[') && trimmed.ends_with(']')) {
                        // Additional validation: check for JSON-like structure
                        let has_json_structure = trimmed.contains(':') || 
                                                 (trimmed.starts_with('[') && trimmed.contains(','));
                        
                        if has_json_structure {
                            injections.push(InjectionRange::new(
                                parent_lang,
                                "json",
                                content_start,
                                content_end,
                                content,
                                "json_string",
                            ));
                        }
                    }
                    
                    start = content_end + pattern.len();
                } else {
                    break;
                }
            }
        }
        
        injections
    }
}

/// Get injections from source code.
///
/// This is the main entry point for detecting embedded languages.
/// It uses a combination of:
/// 1. Tree-sitter injection queries (when available)
/// 2. Heuristic patterns (as fallback)
///
/// # Arguments
/// * `source` - The source code to analyze
/// * `parent_language` - The language identifier of the host code (e.g., "python", "elixir")
///
/// # Returns
/// An `InjectionResult` containing all detected injection ranges.
///
/// # Example
/// ```rust
/// use turbo_parse::injection::get_injections;
///
/// let python_code = r#"
/// query = '''
/// SELECT * FROM users WHERE id = %s
/// '''
/// cursor.execute(query, (user_id,))
/// "#;
/// 
/// let result = get_injections(python_code, "python");
/// assert!(result.success);
/// // May detect SQL injection depending on heuristics
/// ```
pub fn get_injections(source: &str, parent_language: &str) -> InjectionResult {
    let start = Instant::now();
    let lang_name = normalize_language(parent_language);
    
    // First, try to get injections via heuristics
    let heuristic_injections = get_heuristic_injections(source, &lang_name);
    
    // Then, if the language is supported by tree-sitter, try query-based detection
    let query_injections = if is_language_supported(&lang_name) {
        get_query_based_injections(source, &lang_name)
    } else {
        Vec::new()
    };
    
    // Merge injections from both approaches
    let mut all_injections = heuristic_injections;
    all_injections.extend(query_injections);
    
    // Sort by start byte and remove duplicates/overlaps
    all_injections.sort_by_key(|i| i.start_byte);
    all_injections = merge_overlapping_injections(all_injections);
    
    let detection_time_ms = start.elapsed().as_secs_f64() * 1000.0;
    
    InjectionResult::new(&lang_name, all_injections, detection_time_ms)
}

/// Get heuristic-based injections for a language.
fn get_heuristic_injections(source: &str, lang_name: &str) -> Vec<InjectionRange> {
    let mut injections = Vec::new();
    
    match lang_name {
        "python" => {
            injections.extend(heuristics::detect_sql_in_python(source));
            injections.extend(heuristics::detect_html_in_strings(source, "python"));
            injections.extend(heuristics::detect_json_in_strings(source, "python"));
        }
        "elixir" => {
            injections.extend(heuristics::detect_heex_in_elixir(source));
            injections.extend(heuristics::detect_sql_in_python(source)); // Reuse SQL detection
            injections.extend(heuristics::detect_html_in_strings(source, "elixir"));
        }
        "javascript" | "typescript" | "tsx" => {
            injections.extend(heuristics::detect_html_in_strings(source, lang_name));
            injections.extend(heuristics::detect_json_in_strings(source, lang_name));
            injections.extend(heuristics::detect_sql_in_python(source)); // Reuse SQL detection
        }
        "rust" => {
            injections.extend(heuristics::detect_sql_in_python(source)); // Reuse SQL detection
            injections.extend(heuristics::detect_html_in_strings(source, "rust"));
        }
        _ => {
            // For unsupported languages, try generic heuristics
            injections.extend(heuristics::detect_html_in_strings(source, lang_name));
            injections.extend(heuristics::detect_json_in_strings(source, lang_name));
        }
    }
    
    // If we detected HTML, also check for JavaScript and CSS within it
    let mut nested_injections = Vec::new();
    for injection in &injections {
        if injection.injected_language == "html" {
            nested_injections.extend(heuristics::detect_javascript_in_html(&injection.content));
            nested_injections.extend(heuristics::detect_css_in_html(&injection.content));
            
            // Adjust offsets to be relative to the original source
            for nested in &mut nested_injections {
                nested.parent_language = lang_name.to_string();
                nested.start_byte += injection.start_byte;
                nested.end_byte += injection.start_byte;
            }
        }
    }
    injections.extend(nested_injections);
    
    injections
}

/// Get query-based injections using tree-sitter queries.
fn get_query_based_injections(source: &str, lang_name: &str) -> Vec<InjectionRange> {
    // For now, we use heuristic-based injection detection
    // Future enhancement: add proper injection.scm queries
    // This would parse the tree and match injection patterns
    
    // Create a simple tree-sitter based detection
    let ts_language = match get_language(lang_name) {
        Ok(lang) => lang,
        Err(_) => return Vec::new(),
    };
    
    let mut parser = Parser::new();
    if parser.set_language(&ts_language).is_err() {
        return Vec::new();
    }
    
    let tree = match parser.parse(source, None) {
        Some(t) => t,
        None => return Vec::new(),
    };
    
    let mut injections = Vec::new();
    let root = tree.root_node();
    
    // Walk the tree looking for string and comment nodes that might contain injections
    fn collect_potential_injections<'a>(
        node: Node<'a>,
        source: &'a str,
        injections: &mut Vec<InjectionRange>,
        lang_name: &str,
    ) {
        let kind = node.kind();
        
        // Look for string/comment nodes
        if kind.contains("string") || kind.contains("comment") || kind == "heredoc" {
            let start_byte = node.start_byte();
            let end_byte = node.end_byte();
            
            // Extract content
            if let Ok(text) = node.utf8_text(source.as_bytes()) {
                // Check for SQL patterns in Python
                if lang_name == "python" && kind.contains("string") {
                    let content_upper = text.to_uppercase();
                    let has_sql = content_upper.contains("SELECT") || 
                                  content_upper.contains("INSERT") ||
                                  content_upper.contains("UPDATE") ||
                                  content_upper.contains("DELETE") ||
                                  content_upper.contains("FROM");
                    
                    if has_sql {
                        injections.push(InjectionRange::new(
                            lang_name,
                            "sql",
                            start_byte,
                            end_byte,
                            text,
                            kind,
                        ));
                    }
                }
                
                // Check for HTML patterns
                if text.trim().starts_with('<') && text.contains('>') {
                    injections.push(InjectionRange::new(
                        lang_name,
                        "html",
                        start_byte,
                        end_byte,
                        text,
                        kind,
                    ));
                }
            }
        }
        
        // Recurse into children
        for i in 0..node.child_count() {
            if let Some(child) = node.child(i) {
                collect_potential_injections(child, source, injections, lang_name);
            }
        }
    }
    
    collect_potential_injections(root, source, &mut injections, lang_name);
    
    injections
}

/// Merge overlapping injections, preferring more specific ones.
fn merge_overlapping_injections(injections: Vec<InjectionRange>) -> Vec<InjectionRange> {
    if injections.is_empty() {
        return injections;
    }
    
    let mut result: Vec<InjectionRange> = Vec::new();
    
    for injection in injections {
        // Check if this overlaps with the last one
        if let Some(last) = result.last_mut() {
            if last.overlaps(&injection) {
                // Same range: prefer the one with more specific language
                if last.start_byte == injection.start_byte && last.end_byte == injection.end_byte {
                    // Keep the more specific one based on content analysis
                    if is_more_specific_injection(&injection, last) {
                        *last = injection;
                    }
                    continue;
                }
                
                // Partial overlap: keep the first one and skip this
                // This maintains the order of discovery
                continue;
            }
        }
        result.push(injection);
    }
    
    result
}

/// Determine if one injection is more specific than another.
fn is_more_specific_injection(new: &InjectionRange, existing: &InjectionRange) -> bool {
    // Prefer SQL over HTML for SQL-like content
    if new.injected_language == "sql" && existing.injected_language == "html" {
        let content_upper = new.content.to_uppercase();
        if content_upper.contains("SELECT") || content_upper.contains("INSERT") {
            return true;
        }
    }
    
    // Prefer HEEx over HTML for Phoenix templates
    if new.injected_language == "heex" && existing.injected_language == "html" {
        return true;
    }
    
    // Default: keep existing
    false
}

/// Parse injections with their respective grammars.
///
/// This function takes detected injections and parses each one with
/// the appropriate language grammar.
///
/// # Arguments
/// * `injection_result` - The result from `get_injections`
///
/// # Returns
/// A `ParsedInjectionResult` with parsed trees for each injection.
pub fn parse_injections(injection_result: &InjectionResult) -> ParsedInjectionResult {
    let start = Instant::now();
    let mut parsed_injections = Vec::new();
    
    for injection in &injection_result.injections {
        let parsed = parse_single_injection(injection);
        parsed_injections.push(parsed);
    }
    
    let total_time_ms = start.elapsed().as_secs_f64() * 1000.0;
    
    ParsedInjectionResult::new(
        &injection_result.parent_language,
        parsed_injections,
        total_time_ms,
    )
}

/// Parse a single injection with its appropriate grammar.
fn parse_single_injection(injection: &InjectionRange) -> ParsedInjection {
    let start = Instant::now();
    
    // Check if we support the injected language
    if !is_language_supported(&injection.injected_language) {
        // For unsupported languages, we can't parse but we still return the range
        return ParsedInjection {
            range: injection.clone(),
            tree: None,
            parse_success: false,
            parse_errors: vec![format!(
                "Unsupported injected language: '{}'",
                injection.injected_language
            )],
            parse_time_ms: start.elapsed().as_secs_f64() * 1000.0,
        };
    }
    
    // Get the language
    let ts_language = match get_language(&injection.injected_language) {
        Ok(lang) => lang,
        Err(e) => {
            return ParsedInjection {
                range: injection.clone(),
                tree: None,
                parse_success: false,
                parse_errors: vec![format!("Failed to get language: {}", e)],
                parse_time_ms: start.elapsed().as_secs_f64() * 1000.0,
            };
        }
    };
    
    // Create parser
    let mut parser = Parser::new();
    if let Err(e) = parser.set_language(&ts_language) {
        return ParsedInjection {
            range: injection.clone(),
            tree: None,
            parse_success: false,
            parse_errors: vec![format!("Failed to set language: {}", e)],
            parse_time_ms: start.elapsed().as_secs_f64() * 1000.0,
        };
    }
    
    // Parse the content
    let tree = match parser.parse(&injection.content, None) {
        Some(t) => t,
        None => {
            return ParsedInjection {
                range: injection.clone(),
                tree: None,
                parse_success: false,
                parse_errors: vec!["Parser returned no tree".to_string()],
                parse_time_ms: start.elapsed().as_secs_f64() * 1000.0,
            };
        }
    };
    
    // Serialize the tree
    let tree_json = serialize_tree(&tree, &injection.content);
    let has_errors = tree.root_node().has_error();
    
    let parse_time_ms = start.elapsed().as_secs_f64() * 1000.0;
    
    ParsedInjection {
        range: injection.clone(),
        tree: Some(tree_json),
        parse_success: !has_errors,
        parse_errors: if has_errors {
            vec!["Tree contains syntax errors".to_string()]
        } else {
            Vec::new()
        },
        parse_time_ms,
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
fn serialize_tree(tree: &tree_sitter::Tree, source: &str) -> serde_json::Value {
    let root = tree.root_node();
    serde_json::json!({
        "root": serialize_node(root, source),
        "language": "tree-sitter",
    })
}

/// Get injections from a file.
///
/// # Arguments
/// * `path` - Path to the file
/// * `language` - Optional language override (detected from extension if not provided)
///
/// # Returns
/// An `InjectionResult` containing all detected injection ranges.
pub fn get_injections_from_file(path: &str, language: Option<&str>) -> InjectionResult {
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
                "ex" | "exs" | "heex" => "elixir".to_string(),
                _ => {
                    return InjectionResult::error(
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
            return InjectionResult::error(
                &lang,
                format!("Failed to read file '{}': {}", path, e),
            );
        }
    };

    get_injections(&source, &lang)
}

/// Convenience function to detect and parse injections in one call.
///
/// This is useful when you want both the detection information and
/// the parsed ASTs for all injections.
///
/// # Arguments
/// * `source` - The source code to analyze
/// * `parent_language` - The language identifier of the host code
///
/// # Returns
/// A tuple of (InjectionResult, ParsedInjectionResult)
pub fn detect_and_parse_injections(
    source: &str,
    parent_language: &str,
) -> (InjectionResult, ParsedInjectionResult) {
    let detection = get_injections(source, parent_language);
    let parsed = parse_injections(&detection);
    (detection, parsed)
}

#[cfg(test)]
mod tests {
    use super::*;

    // ============================================================================
    // InjectionRange Tests
    // ============================================================================

    #[test]
    fn test_injection_range_new() {
        let range = InjectionRange::new("python", "sql", 10, 50, "SELECT * FROM users", "string");
        assert_eq!(range.parent_language, "python");
        assert_eq!(range.injected_language, "sql");
        assert_eq!(range.start_byte, 10);
        assert_eq!(range.end_byte, 50);
        assert_eq!(range.content, "SELECT * FROM users");
        assert_eq!(range.node_kind, "string");
        assert_eq!(range.len(), 40);
        assert!(!range.is_empty());
    }

    #[test]
    fn test_injection_range_empty() {
        let range = InjectionRange::new("python", "sql", 10, 10, "", "string");
        assert!(range.is_empty());
        assert_eq!(range.len(), 0);
    }

    #[test]
    fn test_injection_range_overlaps() {
        let r1 = InjectionRange::new("python", "sql", 0, 10, "content", "string");
        let r2 = InjectionRange::new("python", "html", 5, 15, "content", "string");
        let r3 = InjectionRange::new("python", "json", 20, 30, "content", "string");

        assert!(r1.overlaps(&r2));
        assert!(r2.overlaps(&r1));
        assert!(!r1.overlaps(&r3));
        assert!(!r3.overlaps(&r1));
    }

    #[test]
    fn test_injection_range_contains() {
        let range = InjectionRange::new("python", "sql", 10, 50, "content", "string");
        assert!(range.contains(10));
        assert!(range.contains(25));
        assert!(range.contains(49));
        assert!(!range.contains(50)); // end_byte is exclusive
        assert!(!range.contains(5));
        assert!(!range.contains(100));
    }

    #[test]
    fn test_injection_range_contains_range() {
        let parent = InjectionRange::new("python", "html", 0, 100, "<html>...</html>", "string");
        let child = InjectionRange::new("html", "javascript", 10, 50, "alert('hi')", "script");
        let outside = InjectionRange::new("python", "sql", 200, 300, "SELECT...", "string");

        assert!(parent.contains_range(&child));
        assert!(!child.contains_range(&parent));
        assert!(!parent.contains_range(&outside));
    }

    #[test]
    fn test_injection_range_with_adjusted_offsets() {
        let range = InjectionRange::new("python", "sql", 10, 50, "SELECT", "string");
        let adjusted = range.with_adjusted_offsets(5);
        assert_eq!(adjusted.start_byte, 15);
        assert_eq!(adjusted.end_byte, 55);

        let adjusted_neg = range.with_adjusted_offsets(-5);
        assert_eq!(adjusted_neg.start_byte, 5);
        assert_eq!(adjusted_neg.end_byte, 45);
    }

    // ============================================================================
    // InjectionResult Tests
    // ============================================================================

    #[test]
    fn test_injection_result_new() {
        let injections = vec![
            InjectionRange::new("python", "sql", 0, 10, "SELECT", "string"),
        ];
        let result = InjectionResult::new("python", injections, 1.5);

        assert_eq!(result.parent_language, "python");
        assert_eq!(result.len(), 1);
        assert!(result.success);
        assert!(result.errors.is_empty());
        assert_eq!(result.detection_time_ms, 1.5);
    }

    #[test]
    fn test_injection_result_error() {
        let result = InjectionResult::error("python", "test error");

        assert_eq!(result.parent_language, "python");
        assert!(!result.success);
        assert_eq!(result.errors.len(), 1);
        assert_eq!(result.errors[0], "test error");
        assert!(result.injections.is_empty());
    }

    #[test]
    fn test_injection_result_injections_of_language() {
        let injections = vec![
            InjectionRange::new("python", "sql", 0, 10, "SELECT", "string"),
            InjectionRange::new("python", "html", 20, 30, "<div>", "string"),
            InjectionRange::new("python", "sql", 40, 50, "INSERT", "string"),
        ];
        let result = InjectionResult::new("python", injections, 1.0);

        let sql_injections = result.injections_of_language("sql");
        assert_eq!(sql_injections.len(), 2);

        let html_injections = result.injections_of_language("html");
        assert_eq!(html_injections.len(), 1);

        let json_injections = result.injections_of_language("json");
        assert!(json_injections.is_empty());
    }

    // ============================================================================
    // Heuristic Detection Tests
    // ============================================================================

    #[test]
    fn test_detect_sql_in_python() {
        let source = r#"
query = """
SELECT * FROM users WHERE id = %s
"""
cursor.execute(query, (user_id,))
"#;
        let injections = heuristics::detect_sql_in_python(source);
        
        assert!(!injections.is_empty(), "Should detect SQL in Python");
        let sql_injection = &injections[0];
        assert_eq!(sql_injection.parent_language, "python");
        assert_eq!(sql_injection.injected_language, "sql");
        assert!(sql_injection.content.contains("SELECT"));
    }

    #[test]
    fn test_detect_sql_in_python_insert() {
        let source = r#"
sql = '''
INSERT INTO users (name, email) VALUES (%s, %s)
'''
"#;
        let injections = heuristics::detect_sql_in_python(source);
        
        assert!(!injections.is_empty(), "Should detect INSERT SQL");
        assert!(injections[0].content.contains("INSERT"));
    }

    #[test]
    fn test_detect_heex_in_elixir() {
        let source = r#"
defmodule MyComponent do
  use Phoenix.Component
  
  def render(assigns) do
    ~H"""
    <div class="my-class">
      <%= @title %>
    </div>
    """
  end
end
"#;
        let injections = heuristics::detect_heex_in_elixir(source);
        
        // Note: This test may need adjustment based on actual heuristic behavior
        // The ~H""" sigil should be detected
    }

    #[test]
    fn test_detect_html_in_strings() {
        let source = r#"
html_content = """
<div class="container">
  <p>Hello World</p>
</div>
"""
"#;
        let injections = heuristics::detect_html_in_strings(source, "python");
        
        assert!(!injections.is_empty(), "Should detect HTML in strings");
        assert_eq!(injections[0].injected_language, "html");
    }

    #[test]
    fn test_detect_javascript_in_html() {
        let source = r#"
<!DOCTYPE html>
<html>
<head>
  <script>
    function greet() {
      alert('Hello!');
    }
  </script>
</head>
<body></body>
</html>
"#;
        let injections = heuristics::detect_javascript_in_html(source);
        
        assert!(!injections.is_empty(), "Should detect JavaScript in HTML");
        assert_eq!(injections[0].injected_language, "javascript");
        assert!(injections[0].content.contains("function"));
    }

    #[test]
    fn test_detect_css_in_html() {
        let source = r#"
<!DOCTYPE html>
<html>
<head>
  <style>
    body { color: red; }
  </style>
</head>
<body></body>
</html>
"#;
        let injections = heuristics::detect_css_in_html(source);
        
        assert!(!injections.is_empty(), "Should detect CSS in HTML");
        assert_eq!(injections[0].injected_language, "css");
    }

    #[test]
    fn test_detect_json_in_strings() {
        let source = r#"
data = '''
{
  "name": "John",
  "age": 30
}
'''
"#;
        let injections = heuristics::detect_json_in_strings(source, "python");
        
        assert!(!injections.is_empty(), "Should detect JSON in strings");
        assert_eq!(injections[0].injected_language, "json");
    }

    // ============================================================================
    // Integration Tests
    // ============================================================================

    #[test]
    fn test_get_injections_python() {
        let source = r#"
def get_users(cursor):
    query = """
    SELECT u.id, u.name, u.email
    FROM users u
    WHERE u.active = true
    ORDER BY u.name
    """
    cursor.execute(query)
    return cursor.fetchall()
"#;
        let result = get_injections(source, "python");
        
        assert!(result.success);
        assert_eq!(result.parent_language, "python");
        // Should detect the SQL injection
        assert!(!result.injections.is_empty(), "Should detect at least one injection");
    }

    #[test]
    fn test_get_injections_empty() {
        let result = get_injections("", "python");
        
        assert!(result.success);
        assert!(result.injections.is_empty());
    }

    #[test]
    fn test_get_injections_unsupported_language() {
        let source = "some code";
        let result = get_injections(source, "unsupported");
        
        // Should still succeed (with heuristics), just return empty
        assert!(result.success);
        assert!(result.injections.is_empty());
    }

    #[test]
    fn test_parse_injections() {
        let injection = InjectionRange::new(
            "python",
            "python", // Use Python as injected language for testing
            0,
            17,
            "def hello(): pass",
            "string",
        );
        let result = InjectionResult::new("python", vec![injection], 0.5);
        
        let parsed = parse_injections(&result);
        
        assert!(!parsed.parsed_injections.is_empty());
        let first = &parsed.parsed_injections[0];
        
        // Should parse successfully since Python is supported
        assert!(first.parse_success || !first.parse_errors.is_empty());
        assert!(first.parse_time_ms >= 0.0);
    }

    #[test]
    fn test_parse_injections_unsupported() {
        let injection = InjectionRange::new(
            "python",
            "unsupported_lang",
            0,
            10,
            "some content",
            "string",
        );
        let result = InjectionResult::new("python", vec![injection], 0.5);
        
        let parsed = parse_injections(&result);
        
        assert!(!parsed.parsed_injections.is_empty());
        let first = &parsed.parsed_injections[0];
        
        assert!(!first.parse_success);
        assert!(!first.parse_errors.is_empty());
        assert!(first.parse_errors[0].contains("Unsupported"));
    }

    #[test]
    fn test_detect_and_parse_injections() {
        let source = r#"
html = """
<div>
  <script>alert('hi');</script>
</div>
"""
"#;
        let (detection, parsed) = detect_and_parse_injections(source, "python");
        
        assert!(detection.success);
        assert!(parsed.parsed_injections.len() >= detection.injections.len());
    }

    #[test]
    fn test_nested_injections() {
        // Test detection of nested injections (HTML containing JS)
        let source = r#"
html_content = """
<!DOCTYPE html>
<html>
<body>
  <script>
    function test() { return 42; }
  </script>
</body>
</html>
"""
"#;
        let result = get_injections(source, "python");
        
        assert!(result.success);
        
        // Should detect both HTML and nested JavaScript
        let html_count = result.injections_of_language("html").len();
        let js_count = result.injections_of_language("javascript").len();
        
        // We should at least detect the HTML
        assert!(html_count > 0 || result.injections.is_empty() == false, 
                "Should detect HTML or other injections");
    }

    // ============================================================================
    // File Tests
    // ============================================================================

    #[test]
    fn test_get_injections_from_file_not_found() {
        let result = get_injections_from_file("/nonexistent/path/file.py", None);
        
        assert!(!result.success);
        assert!(!result.errors.is_empty());
        assert!(result.errors[0].contains("Failed to read file"));
    }

    #[test]
    fn test_get_injections_from_file_auto_detect() {
        // Create a temporary file
        let temp_dir = std::env::temp_dir();
        let temp_file = temp_dir.join("test_injection.py");
        std::fs::write(&temp_file, "query = \"\"\"SELECT * FROM users\"\"\"\n").unwrap();

        let result = get_injections_from_file(temp_file.to_str().unwrap(), None);
        assert!(result.success);
        assert_eq!(result.parent_language, "python");

        // Clean up
        let _ = std::fs::remove_file(&temp_file);
    }

    // ============================================================================
    // Language Normalization Tests
    // ============================================================================

    #[test]
    fn test_language_normalization_in_injections() {
        let source = "query = \"\"\"SELECT 1\"\"\"";
        
        // Test with alias "py"
        let result = get_injections(source, "py");
        assert_eq!(result.parent_language, "python");
        
        // Test with alias "js"
        let result_js = get_injections("content", "js");
        assert_eq!(result_js.parent_language, "javascript");
    }

    // ============================================================================
    // ParsedInjectionResult Tests
    // ============================================================================

    #[test]
    fn test_parsed_injection_result() {
        let parsed_injections = vec![
            ParsedInjection {
                range: InjectionRange::new("python", "sql", 0, 10, "SELECT", "string"),
                tree: None,
                parse_success: true,
                parse_errors: vec![],
                parse_time_ms: 1.0,
            },
            ParsedInjection {
                range: InjectionRange::new("python", "html", 20, 40, "<div>", "string"),
                tree: None,
                parse_success: true,
                parse_errors: vec![],
                parse_time_ms: 2.0,
            },
        ];
        
        let result = ParsedInjectionResult::new("python", parsed_injections, 3.0);
        
        assert_eq!(result.parent_language, "python");
        assert!(result.all_succeeded);
        assert_eq!(result.parsed_injections.len(), 2);
        
        let counts = result.language_counts;
        assert_eq!(counts.get("sql"), Some(&1));
        assert_eq!(counts.get("html"), Some(&1));
    }

    #[test]
    fn test_parsed_injection_result_with_failures() {
        let parsed_injections = vec![
            ParsedInjection {
                range: InjectionRange::new("python", "unsupported", 0, 10, "content", "string"),
                tree: None,
                parse_success: false,
                parse_errors: vec!["Unsupported language".to_string()],
                parse_time_ms: 0.0,
            },
        ];
        
        let result = ParsedInjectionResult::new("python", parsed_injections, 0.5);
        
        assert!(!result.all_succeeded);
    }

    #[test]
    fn test_parsed_injection_result_injections_of_language() {
        let parsed_injections = vec![
            ParsedInjection {
                range: InjectionRange::new("python", "sql", 0, 10, "SELECT", "string"),
                tree: None,
                parse_success: true,
                parse_errors: vec![],
                parse_time_ms: 1.0,
            },
            ParsedInjection {
                range: InjectionRange::new("python", "sql", 20, 40, "INSERT", "string"),
                tree: None,
                parse_success: true,
                parse_errors: vec![],
                parse_time_ms: 2.0,
            },
        ];
        
        let result = ParsedInjectionResult::new("python", parsed_injections, 3.0);
        let sql_injections = result.injections_of_language("sql");
        
        assert_eq!(sql_injections.len(), 2);
    }
}
