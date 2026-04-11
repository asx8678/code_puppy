//! Single-pass pruning, filtering, truncation, and summarization splitting.

use pyo3::prelude::*;
use pyo3::types::PyList;
use rustc_hash::FxHashSet;

use crate::token_estimation::{estimate_tokens, stringify_part_for_tokens};
use crate::types::Message;
use crate::{PruneResult, SplitResult};

/// Core pruning logic that operates on already-parsed messages.
pub fn prune_and_filter_core(
    msgs: &[Message],
    max_tokens_per_message: i64,
) -> PruneResult {
    let mut call_ids = FxHashSet::default();
    let mut return_ids = FxHashSet::default();
    for msg in msgs {
        for part in &msg.parts {
            if let Some(ref id) = part.tool_call_id {
                if !id.is_empty() {
                    if part.part_kind == "tool-call" {
                        call_ids.insert(id.clone());
                    } else {
                        return_ids.insert(id.clone());
                    }
                }
            }
        }
    }
    let mismatched: FxHashSet<String> = call_ids
        .symmetric_difference(&return_ids)
        .cloned()
        .collect();

    let mut surviving = Vec::new();
    for (i, msg) in msgs.iter().enumerate() {
        if msg.parts.iter().any(|p| {
            p.tool_call_id
                .as_ref()
                .is_some_and(|id| mismatched.contains(id.as_str()))
        }) {
            continue;
        }
        let tokens: i64 = msg
            .parts
            .iter()
            .map(|p| estimate_tokens(&stringify_part_for_tokens(p)))
            .sum();
        if tokens >= max_tokens_per_message {
            continue;
        }
        if msg.parts.len() == 1
            && msg.parts[0].part_kind == "thinking"
            && msg.parts[0].content.as_ref().is_none_or(|c| c.is_empty())
        {
            continue;
        }
        surviving.push(i);
    }

    let pending = call_ids.difference(&return_ids).count();
    PruneResult {
        dropped_count: msgs.len() - surviving.len(),
        surviving_indices: surviving,
        had_pending_tool_calls: pending > 0,
        pending_tool_call_count: pending,
    }
}

/// Wrapper that parses PyList then calls the core implementation.
pub fn prune_and_filter_impl(
    messages: &Bound<'_, PyList>,
    max_tokens_per_message: i64,
) -> PyResult<PruneResult> {
    let msgs: Vec<Message> = messages
        .iter()
        .map(|o| Message::from_py(&o))
        .collect::<PyResult<_>>()?;
    Ok(prune_and_filter_core(&msgs, max_tokens_per_message))
}

pub fn truncation_indices_impl(
    per_message_tokens: &[i64],
    protected_tokens: i64,
    second_has_thinking: bool,
) -> Vec<usize> {
    if per_message_tokens.is_empty() {
        return vec![];
    }
    let mut result = vec![0usize];
    let start_idx = if second_has_thinking && per_message_tokens.len() > 1 {
        result.push(1);
        2
    } else {
        1
    };
    let mut budget = protected_tokens;
    let mut tail = Vec::new();
    for i in (start_idx..per_message_tokens.len()).rev() {
        if budget - per_message_tokens[i] < 0 {
            break;
        }
        budget -= per_message_tokens[i];
        tail.push(i);
    }
    tail.reverse();
    result.extend(tail);
    result
}

/// Extract tool call IDs from messages for summarization logic.
fn extract_tool_call_ids_from_messages(msgs: &[Message]) -> Vec<Vec<(String, String)>> {
    msgs.iter()
        .map(|msg| {
            msg.parts
                .iter()
                .filter(|p| {
                    p.part_kind == "tool-call"
                        || p.part_kind == "tool-return"
                        || p.part_kind == "tool_return"
                })
                .filter_map(|p| {
                    p.tool_call_id
                        .as_ref()
                        .map(|id| (id.clone(), p.part_kind.clone()))
                })
                .collect()
        })
        .collect()
}

/// Core implementation that works with cached messages and token counts.
pub fn split_for_summarization_core(
    per_message_tokens: &[i64],
    msgs: &[Message],
    protected_tokens_limit: i64,
) -> SplitResult {
    if per_message_tokens.len() <= 1 {
        return SplitResult {
            summarize_indices: vec![],
            protected_indices: (0..per_message_tokens.len()).collect(),
            protected_token_count: per_message_tokens.iter().sum(),
        };
    }
    let mut prot_tok = per_message_tokens[0];
    let mut prot_tail = Vec::new();
    for i in (1..per_message_tokens.len()).rev() {
        if prot_tok + per_message_tokens[i] > protected_tokens_limit {
            break;
        }
        prot_tail.push(i);
        prot_tok += per_message_tokens[i];
    }
    prot_tail.reverse();

    let prot_start = prot_tail
        .first()
        .copied()
        .unwrap_or(per_message_tokens.len());
    let mut adj = prot_start;
    if adj > 1 && !msgs.is_empty() {
        let tool_call_ids_per_message = extract_tool_call_ids_from_messages(msgs);
        let mut ret_ids = FxHashSet::default();
        for &idx in &prot_tail {
            if idx < tool_call_ids_per_message.len() {
                for (id, kind) in &tool_call_ids_per_message[idx] {
                    if kind == "tool-return" || kind == "tool_return" {
                        ret_ids.insert(id.clone());
                    }
                }
            }
        }
        for i in (1..adj).rev() {
            if i >= tool_call_ids_per_message.len() {
                continue;
            }
            if tool_call_ids_per_message[i]
                .iter()
                .any(|(id, k)| (k == "tool-call" || k == "tool_call") && ret_ids.contains(id))
            {
                adj = i;
            } else {
                break;
            }
        }
    }

    let summarize_indices: Vec<usize> = (1..adj).collect();
    let mut protected_indices = vec![0usize];
    protected_indices.extend(adj..per_message_tokens.len());
    let protected_token_count = protected_indices
        .iter()
        .map(|&i| per_message_tokens[i])
        .sum();

    SplitResult {
        summarize_indices,
        protected_indices,
        protected_token_count,
    }
}

/// Wrapper that takes pre-extracted tool_call_ids (backward-compatible).
pub fn split_for_summarization_impl(
    per_message_tokens: &[i64],
    tool_call_ids_per_message: &[Vec<(String, String)>],
    protected_tokens_limit: i64,
) -> SplitResult {
    // Convert Vec<Vec<(String, String)>> to Message-like structure is non-trivial,
    // so we use the original logic directly
    if per_message_tokens.len() <= 1 {
        return SplitResult {
            summarize_indices: vec![],
            protected_indices: (0..per_message_tokens.len()).collect(),
            protected_token_count: per_message_tokens.iter().sum(),
        };
    }
    let mut prot_tok = per_message_tokens[0];
    let mut prot_tail = Vec::new();
    for i in (1..per_message_tokens.len()).rev() {
        if prot_tok + per_message_tokens[i] > protected_tokens_limit {
            break;
        }
        prot_tail.push(i);
        prot_tok += per_message_tokens[i];
    }
    prot_tail.reverse();

    let prot_start = prot_tail
        .first()
        .copied()
        .unwrap_or(per_message_tokens.len());
    let mut adj = prot_start;
    if adj > 1 && !tool_call_ids_per_message.is_empty() {
        let mut ret_ids = FxHashSet::default();
        for &idx in &prot_tail {
            if idx < tool_call_ids_per_message.len() {
                for (id, kind) in &tool_call_ids_per_message[idx] {
                    if kind == "tool-return" || kind == "tool_return" {
                        ret_ids.insert(id.clone());
                    }
                }
            }
        }
        for i in (1..adj).rev() {
            if i >= tool_call_ids_per_message.len() {
                continue;
            }
            if tool_call_ids_per_message[i]
                .iter()
                .any(|(id, k)| (k == "tool-call" || k == "tool_call") && ret_ids.contains(id))
            {
                adj = i;
            } else {
                break;
            }
        }
    }

    let summarize_indices: Vec<usize> = (1..adj).collect();
    let mut protected_indices = vec![0usize];
    protected_indices.extend(adj..per_message_tokens.len());
    let protected_token_count = protected_indices
        .iter()
        .map(|&i| per_message_tokens[i])
        .sum();

    SplitResult {
        summarize_indices,
        protected_indices,
        protected_token_count,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn test_truncation_keeps_first() {
        let r = truncation_indices_impl(&[100, 200, 300, 400, 500], 600, false);
        assert_eq!(r[0], 0);
        assert!(r.contains(&4));
    }
    #[test]
    fn test_truncation_empty() {
        assert!(truncation_indices_impl(&[], 1000, false).is_empty());
    }
}
