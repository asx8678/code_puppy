//! Token estimation and batch message processing.

use pyo3::prelude::*;
use pyo3::types::PyList;

use crate::message_hashing::hash_message;
use crate::types::{Message, MessagePart, ToolDefinition};
use crate::ProcessResult;

pub fn estimate_tokens(text: &str) -> i64 {
    std::cmp::max(1, (text.chars().count() as f64 / 2.5).floor() as i64)
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
            if !desc.is_empty() { total += estimate_tokens(desc); }
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
    let msgs: Vec<Message> = messages.iter().map(|o| Message::from_py(&o)).collect::<PyResult<_>>()?;
    let tool_defs: Vec<ToolDefinition> = tool_definitions.iter().map(|o| ToolDefinition::from_py(&o)).collect::<PyResult<_>>()?;
    let mcp_defs: Vec<ToolDefinition> = mcp_tool_definitions.iter().map(|o| ToolDefinition::from_py(&o)).collect::<PyResult<_>>()?;

    let mut per_message_tokens = Vec::with_capacity(msgs.len());
    let mut message_hashes = Vec::with_capacity(msgs.len());
    let mut total_message_tokens: i64 = 0;

    for msg in &msgs {
        let mut msg_tokens: i64 = 0;
        for part in &msg.parts {
            let s = stringify_part_for_tokens(part);
            if !s.is_empty() { msg_tokens += estimate_tokens(&s); }
        }
        msg_tokens = std::cmp::max(1, msg_tokens);
        per_message_tokens.push(msg_tokens);
        total_message_tokens += msg_tokens;
        message_hashes.push(hash_message(msg));
    }

    let context_overhead = estimate_context_overhead(&tool_defs, &mcp_defs, system_prompt);

    Ok(ProcessResult { per_message_tokens, total_message_tokens, context_overhead_tokens: context_overhead, message_hashes })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn test_estimate_tokens_empty() { assert_eq!(estimate_tokens(""), 1); }
    #[test] fn test_estimate_tokens_hello() { assert_eq!(estimate_tokens("Hello, world!"), 5); }
    #[test] fn test_estimate_tokens_large() { assert_eq!(estimate_tokens(&"x".repeat(3000)), 1200); }
}
