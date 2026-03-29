//! Fast message hashing using FxHash.
//!
//! Replaces `BaseAgent._stringify_part()` + `hash_message()` with FxHash-based
//! hashing. Hash values do NOT need to match Python `hash()` — they are only
//! compared within the same process session.

use rustc_hash::FxHasher;
use std::hash::{Hash, Hasher};

use crate::types::{Message, MessagePart};

/// Build the canonical string for a part (for hashing).
///
/// Mirrors `BaseAgent._stringify_part()` in Python.
fn stringify_part_for_hash(part: &MessagePart) -> String {
    let mut attributes: Vec<String> = Vec::with_capacity(6);

    // Class name equivalent (part_kind)
    attributes.push(part.part_kind.clone());

    // Role/instructions (from part-level, if present — typically on message level)
    // Note: These are checked via hasattr in Python; here we just skip if None

    if let Some(ref tool_call_id) = part.tool_call_id {
        if !tool_call_id.is_empty() {
            attributes.push(format!("tool_call_id={tool_call_id}"));
        }
    }

    if let Some(ref tool_name) = part.tool_name {
        if !tool_name.is_empty() {
            attributes.push(format!("tool_name={tool_name}"));
        }
    }

    // Content handling — mirrors the Python isinstance chain
    if let Some(ref content) = part.content {
        attributes.push(format!("content={content}"));
    } else if let Some(ref json) = part.content_json {
        attributes.push(format!("content={json}"));
    } else {
        attributes.push("content=None".to_string());
    }

    attributes.join("|")
}

/// Compute a stable FxHash for a message.
///
/// Mirrors `BaseAgent.hash_message()` — builds a canonical string from
/// header bits + part strings, then hashes it.
pub fn hash_message(msg: &Message) -> i64 {
    let mut header_bits: Vec<String> = Vec::new();

    if let Some(ref role) = msg.role {
        if !role.is_empty() {
            header_bits.push(format!("role={role}"));
        }
    }
    if let Some(ref instructions) = msg.instructions {
        if !instructions.is_empty() {
            header_bits.push(format!("instructions={instructions}"));
        }
    }

    let part_strings: Vec<String> = msg.parts.iter().map(stringify_part_for_hash).collect();

    let mut all_parts = header_bits;
    all_parts.extend(part_strings);
    let canonical = all_parts.join("||");

    let mut hasher = FxHasher::default();
    canonical.hash(&mut hasher);
    hasher.finish() as i64
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::MessagePart;

    fn make_text_part(content: &str) -> MessagePart {
        MessagePart {
            part_kind: "text".to_string(),
            content: Some(content.to_string()),
            content_json: None,
            tool_call_id: None,
            tool_name: None,
            args: None,
        }
    }

    #[test]
    fn test_same_message_same_hash() {
        let msg1 = Message {
            kind: "request".to_string(),
            role: Some("user".to_string()),
            instructions: None,
            parts: vec![make_text_part("hello")],
        };
        let msg2 = msg1.clone();
        assert_eq!(hash_message(&msg1), hash_message(&msg2));
    }

    #[test]
    fn test_different_message_different_hash() {
        let msg1 = Message {
            kind: "request".to_string(),
            role: Some("user".to_string()),
            instructions: None,
            parts: vec![make_text_part("hello")],
        };
        let msg2 = Message {
            kind: "request".to_string(),
            role: Some("user".to_string()),
            instructions: None,
            parts: vec![make_text_part("world")],
        };
        assert_ne!(hash_message(&msg1), hash_message(&msg2));
    }
}
