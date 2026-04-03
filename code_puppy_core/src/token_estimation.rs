//! Token estimation and batch message processing.

use pyo3::prelude::*;
use pyo3::types::PyList;

use crate::message_hashing::hash_message;
use crate::types::{Message, MessagePart, ToolDefinition};
use crate::ProcessResult;

// Threshold above which we switch to line-sampling.
const SAMPLING_THRESHOLD: usize = 500;

// Minimum ratio for code detection: >30% of lines must have code indicators
const CODE_DETECTION_RATIO: f64 = 0.3;

/// Check if a line contains code indicators (braces, brackets, semicolons, keywords).
fn line_has_code_indicators(line: &str) -> bool {
    // Check for braces, brackets, parentheses, semicolons
    if line.chars().any(|c| matches!(c, '{' | '}' | '[' | ']' | '(' | ')' | ';')) {
        return true;
    }

    // Check for language keywords at start of line (after optional whitespace)
    let trimmed = line.trim_start();

    // Python keywords
    if trimmed.starts_with("def ")
        || trimmed.starts_with("class ")
        || trimmed.starts_with("import ")
        || trimmed.starts_with("from ")
        || trimmed.starts_with("if ")
        || trimmed.starts_with("for ")
        || trimmed.starts_with("while ")
        || trimmed.starts_with("return ")
    {
        return true;
    }

    // JS/TS keywords
    if trimmed.starts_with("function ")
        || trimmed.starts_with("const ")
        || trimmed.starts_with("let ")
        || trimmed.starts_with("var ")
        || trimmed.starts_with("=>")
    {
        return true;
    }

    // C/C++ keywords
    if trimmed.starts_with("#include") {
        return true;
    }

    false
}

/// Heuristic: does the text look like source code?
/// Uses first 2000 chars to determine, requires >30% of lines to have code indicators.
fn is_code_heavy(text: &str) -> bool {
    let char_count = text.chars().count();
    if char_count < 20 {
        return false;
    }

    // Use first 2000 chars for detection
    let sample: String = text.chars().take(2000).collect();
    let lines: Vec<&str> = sample.lines().collect();
    let line_count = lines.len().max(1);

    let code_lines = lines.iter().filter(|&&line| line_has_code_indicators(line)).count();

    (code_lines as f64) / (line_count as f64) > CODE_DETECTION_RATIO
}

/// Return the estimated characters-per-token ratio for the text.
fn chars_per_token(text: &str) -> f64 {
    if is_code_heavy(text) {
        4.5
    } else {
        4.0
    }
}

/// Estimate the number of tokens in a text string.
///
/// For short texts (<=500 chars) uses a direct character-ratio heuristic.
/// For longer texts, samples ~1% of lines and extrapolates.
/// Code-heavy text uses 4.5 chars/token, prose uses 4.0 chars/token.
pub fn estimate_tokens(text: &str) -> i64 {
    if text.is_empty() {
        return 1;
    }

    let text_len = text.chars().count();
    let ratio = chars_per_token(text);

    // Fast path for short texts — direct division.
    if text_len <= SAMPLING_THRESHOLD {
        return std::cmp::max(1, (text_len as f64 / ratio).floor() as i64);
    }

    // Sampling path for large texts.
    // Split into lines, sample every Nth line, measure the sample,
    // then scale up proportionally.
    let lines: Vec<&str> = text.lines().collect();
    let num_lines = lines.len();

    // Sample ~1% of lines, minimum 1 line
    let step = (num_lines / 100).max(1);

    let mut sample_text_len = 0usize;
    for (i, line) in lines.iter().enumerate() {
        if i % step == 0 {
            sample_text_len += line.chars().count();
            // Account for newline character that lines() strips
            sample_text_len += 1;
        }
    }

    if sample_text_len == 0 {
        return std::cmp::max(1, (text_len as f64 / ratio).floor() as i64);
    }

    // Tokens in the sample
    let sample_tokens = sample_text_len as f64 / ratio;
    // Scale up: (sample_tokens / sample_chars) * total_chars
    let estimated = sample_tokens / (sample_text_len as f64) * (text_len as f64);

    std::cmp::max(1, estimated.floor() as i64)
}

pub fn stringify_part_for_tokens(part: &MessagePart) -> String {
    let mut result = String::new();
    result.push_str(&part.part_kind);
    result.push_str(": ");

    if let Some(ref content) = part.content {
        if !content.is_empty() {
            result.clear();
            result.push_str(content);
        }
    } else if let Some(ref json) = part.content_json {
        result.clear();
        result.push_str(json);
    }

    if let Some(ref tool_name) = part.tool_name {
        result.push_str(tool_name);
        if let Some(ref args) = part.args {
            result.push(' ');
            result.push_str(args);
        }
    }
    result
}

fn estimate_context_overhead(
    tool_defs: &[ToolDefinition],
    mcp_tool_defs: &[ToolDefinition],
    system_prompt: &str,
) -> i64 {
    let mut total: i64 = 0;
    if !system_prompt.is_empty() {
        total += estimate_tokens(system_prompt);
    }
    for tool in tool_defs.iter().chain(mcp_tool_defs.iter()) {
        total += estimate_tokens(&tool.name);
        if let Some(ref desc) = tool.description {
            if !desc.is_empty() {
                total += estimate_tokens(desc);
            }
        }
        if let Some(ref schema) = tool.input_schema {
            let s = serde_json::to_string(schema).unwrap_or_default();
            total += estimate_tokens(&s);
        }
    }
    total
}

pub fn process_messages_batch_impl(
    messages: &Bound<'_, PyList>,
    tool_definitions: &Bound<'_, PyList>,
    mcp_tool_definitions: &Bound<'_, PyList>,
    system_prompt: &str,
) -> PyResult<ProcessResult> {
    let msgs: Vec<Message> = messages
        .iter()
        .map(|o| Message::from_py(&o))
        .collect::<PyResult<_>>()?;
    let tool_defs: Vec<ToolDefinition> = tool_definitions
        .iter()
        .map(|o| ToolDefinition::from_py(&o))
        .collect::<PyResult<_>>()?;
    let mcp_defs: Vec<ToolDefinition> = mcp_tool_definitions
        .iter()
        .map(|o| ToolDefinition::from_py(&o))
        .collect::<PyResult<_>>()?;

    let mut per_message_tokens = Vec::with_capacity(msgs.len());
    let mut message_hashes = Vec::with_capacity(msgs.len());
    let mut total_message_tokens: i64 = 0;

    for msg in &msgs {
        let mut msg_tokens: i64 = 0;
        for part in &msg.parts {
            let s = stringify_part_for_tokens(part);
            if !s.is_empty() {
                msg_tokens += estimate_tokens(&s);
            }
        }
        msg_tokens = std::cmp::max(1, msg_tokens);
        per_message_tokens.push(msg_tokens);
        total_message_tokens += msg_tokens;
        message_hashes.push(hash_message(msg));
    }

    let context_overhead = estimate_context_overhead(&tool_defs, &mcp_defs, system_prompt);

    Ok(ProcessResult {
        per_message_tokens,
        total_message_tokens,
        context_overhead_tokens: context_overhead,
        message_hashes,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_estimate_tokens_empty() {
        assert_eq!(estimate_tokens(""), 1);
    }

    #[test]
    fn test_estimate_tokens_hello_prose() {
        // "Hello, world!" has 13 chars, prose uses 4.0 chars/token
        // 13 / 4.0 = 3.25 -> floor -> 3
        assert_eq!(estimate_tokens("Hello, world!"), 3);
    }

    #[test]
    fn test_estimate_tokens_code_detection() {
        // Code with braces uses 4.5 chars/token
        let code = "fn main() { println!(\"Hello\"); }";
        // 32 chars / 4.5 = 7.11 -> floor -> 7
        assert_eq!(estimate_tokens(code), 7);
    }

    #[test]
    fn test_estimate_tokens_short_prose() {
        // Short text without code indicators, 4.0 chars/token
        let text = "This is a simple sentence for testing.";
        // 38 chars / 4.0 = 9.5 -> floor -> 9
        assert_eq!(estimate_tokens(text), 9);
    }

    #[test]
    fn test_estimate_tokens_sampling_threshold() {
        // Text just over 500 chars triggers sampling path
        // This is prose (no code indicators), so 4.0 chars/token
        let text = "a".repeat(600);
        // 600 / 4.0 = 150
        assert_eq!(estimate_tokens(&text), 150);
    }

    #[test]
    fn test_estimate_tokens_large_prose() {
        // Large prose text without code indicators uses sampling
        let text = "word ".repeat(700); // ~3500 chars of prose
        // No code indicators, so ratio = 4.0
        // Should use sampling path and give approximately 3500/4.0 = 875
        let result = estimate_tokens(&text);
        assert!(result > 800 && result < 950, "Expected ~875, got {}", result);
    }

    #[test]
    fn test_estimate_tokens_large_code() {
        // Large code text with code indicators uses 4.5 ratio
        let code_line = "fn foo() { bar(); }\n";
        let text = code_line.repeat(100); // ~2000 chars of code
        // Has code indicators, so ratio = 4.5
        // Should use sampling path and give approximately 2000/4.5 = 444
        let result = estimate_tokens(&text);
        assert!(result > 400 && result < 500, "Expected ~444, got {}", result);
    }

    #[test]
    fn test_is_code_heavy_detection() {
        // Python function should be detected as code
        let python_code = "def hello():\n    return 'world'\n";
        assert!(is_code_heavy(python_code));

        // Pure prose should not be code
        let prose = "This is just regular text without any code.";
        assert!(!is_code_heavy(prose));

        // Mixed content with enough code indicators (>30%)
        let mixed = "def a():\n    pass\ndef b():\n    pass\nSome text.\n";
        // 4 lines of code out of 5 total = 80% code lines
        assert!(is_code_heavy(mixed));
    }

    #[test]
    fn test_line_has_code_indicators() {
        assert!(line_has_code_indicators("if x > 0:"));
        assert!(line_has_code_indicators("def foo():"));
        assert!(line_has_code_indicators("{\"key\": \"value\"}"));
        assert!(line_has_code_indicators("function test() {}"));
        assert!(line_has_code_indicators("#include <stdio.h>"));
        assert!(!line_has_code_indicators("This is just text."));
        assert!(!line_has_code_indicators("Hello world"));
    }
}
