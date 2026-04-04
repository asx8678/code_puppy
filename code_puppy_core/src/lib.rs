use pyo3::prelude::*;
use pyo3::types::PyList;
use pyo3::types::PyAny;

mod hashline;
mod message_hashing;
mod pruning;
mod serialization;
mod token_estimation;
mod types;

use hashline::{
    compute_line_hash as compute_line_hash_impl,
    format_hashlines as format_hashlines_impl,
    strip_hashline_prefixes as strip_hashline_prefixes_impl,
    validate_hashline_anchor as validate_hashline_anchor_impl,
};
use pruning::{collect_tool_call_ids_impl, prune_and_filter_impl, split_for_summarization_impl, truncation_indices_impl};
use serialization::{
    deserialize_session_impl, serialize_session_impl, serialize_session_incremental_impl,
    serialize_messages_incremental_impl, serialize_session_incremental_new_impl,
    get_incremental_message_count_impl, get_incremental_data_offset_impl,
    append_messages_incremental_impl, deserialize_incremental_with_hashes_impl,
    get_compacted_hashes_offset_impl,
};
use token_estimation::process_messages_batch_impl;

// ── Result types exposed to Python ──────────────────────────────────────────

#[pyclass(frozen)]
#[derive(Debug)]
pub struct ProcessResult {
    #[pyo3(get)]
    pub per_message_tokens: Vec<i64>,
    #[pyo3(get)]
    pub total_message_tokens: i64,
    #[pyo3(get)]
    pub context_overhead_tokens: i64,
    #[pyo3(get)]
    pub message_hashes: Vec<i64>,
}

#[pyclass(frozen)]
#[derive(Debug)]
pub struct PruneResult {
    #[pyo3(get)]
    pub surviving_indices: Vec<usize>,
    #[pyo3(get)]
    pub dropped_count: usize,
    #[pyo3(get)]
    pub had_pending_tool_calls: bool,
    #[pyo3(get)]
    pub pending_tool_call_count: usize,
}

#[pyclass(frozen)]
#[derive(Debug)]
pub struct SplitResult {
    #[pyo3(get)]
    pub summarize_indices: Vec<usize>,
    #[pyo3(get)]
    pub protected_indices: Vec<usize>,
    #[pyo3(get)]
    pub protected_token_count: i64,
}

// ── Helper: parse list[dict] → Vec<Message> ─────────────────────────────────

// ── Python-facing functions ─────────────────────────────────────────────────

#[pyfunction]
#[pyo3(signature = (messages, tool_definitions, mcp_tool_definitions, system_prompt))]
fn process_messages_batch<'py>(
    messages: &Bound<'py, PyList>,
    tool_definitions: &Bound<'py, PyList>,
    mcp_tool_definitions: &Bound<'py, PyList>,
    system_prompt: &str,
) -> PyResult<ProcessResult> {
    process_messages_batch_impl(
        messages,
        tool_definitions,
        mcp_tool_definitions,
        system_prompt,
    )
}

#[pyfunction]
#[pyo3(signature = (messages, max_tokens_per_message=50000))]
fn prune_and_filter(
    messages: &Bound<'_, PyList>,
    max_tokens_per_message: i64,
) -> PyResult<PruneResult> {
    prune_and_filter_impl(messages, max_tokens_per_message)
}

#[pyfunction]
#[pyo3(signature = (per_message_tokens, protected_tokens, second_has_thinking))]
fn truncation_indices(
    per_message_tokens: Vec<i64>,
    protected_tokens: i64,
    second_has_thinking: bool,
) -> PyResult<Vec<usize>> {
    Ok(truncation_indices_impl(
        &per_message_tokens,
        protected_tokens,
        second_has_thinking,
    ))
}

#[pyfunction]
#[pyo3(signature = (per_message_tokens, tool_call_ids_per_message, protected_tokens_limit))]
fn split_for_summarization(
    per_message_tokens: Vec<i64>,
    tool_call_ids_per_message: Vec<Vec<(String, String)>>,
    protected_tokens_limit: i64,
) -> PyResult<SplitResult> {
    Ok(split_for_summarization_impl(
        &per_message_tokens,
        &tool_call_ids_per_message,
        protected_tokens_limit,
    ))
}

#[pyfunction]
#[pyo3(signature = (messages,))]
fn serialize_session(messages: &Bound<'_, PyList>) -> PyResult<Vec<u8>> {
    serialize_session_impl(messages)
}

#[pyfunction]
#[pyo3(signature = (data,))]
fn deserialize_session<'py>(data: &[u8], py: Python<'py>) -> PyResult<Py<PyList>> {
    deserialize_session_impl(py, data)
}

#[pyfunction]
#[pyo3(signature = (new_messages, existing_data=None))]
fn serialize_session_incremental(
    new_messages: &Bound<'_, PyList>,
    existing_data: Option<&[u8]>,
) -> PyResult<Vec<u8>> {
    serialize_session_incremental_impl(new_messages, existing_data)
}

/// Serialize only new messages as length-prefixed bytes for appending.
#[pyfunction]
#[pyo3(signature = (new_messages,))]
fn serialize_messages_incremental(
    new_messages: &Bound<'_, PyList>,
) -> PyResult<Vec<u8>> {
    serialize_messages_incremental_impl(new_messages)
}

/// Create a new incremental format file with all messages and optional compacted_hashes.
#[pyfunction]
#[pyo3(signature = (messages, compacted_hashes=None))]
fn serialize_session_incremental_new(
    messages: &Bound<'_, PyList>,
    compacted_hashes: Option<&Bound<'_, PyList>>,
) -> PyResult<Vec<u8>> {
    serialize_session_incremental_new_impl(messages, compacted_hashes)
}

/// Get message count from incremental format file.
#[pyfunction]
#[pyo3(signature = (data,))]
fn get_incremental_message_count(data: &[u8]) -> PyResult<usize> {
    get_incremental_message_count_impl(data)
}

/// Get data offset after header in incremental format file.
#[pyfunction]
#[pyo3(signature = (data,))]
fn get_incremental_data_offset(data: &[u8]) -> PyResult<usize> {
    get_incremental_data_offset_impl(data)
}

/// Get compacted_hashes offset in incremental format file.
#[pyfunction]
#[pyo3(signature = (data,))]
fn get_compacted_hashes_offset(data: &[u8]) -> PyResult<usize> {
    get_compacted_hashes_offset_impl(data)
}

/// Append new messages to existing incremental file data.
/// Returns new complete file data with updated header and appended messages.
#[pyfunction]
#[pyo3(signature = (existing_data, new_messages))]
fn append_messages_incremental(
    existing_data: &[u8],
    new_messages: &Bound<'_, PyList>,
) -> PyResult<Vec<u8>> {
    append_messages_incremental_impl(existing_data, new_messages)
}

/// Deserialize incremental format including compacted_hashes.
/// Returns (messages, compacted_hashes) tuple.
#[pyfunction]
#[pyo3(signature = (data,))]
fn deserialize_incremental_with_hashes<'py>(
    data: &[u8],
    py: Python<'py>,
) -> PyResult<(Py<PyList>, Vec<String>)> {
    deserialize_incremental_with_hashes_impl(py, data)
}

// ── Hashline functions ──────────────────────────────────────────────────────

#[pyfunction]
fn compute_line_hash(idx: u32, line: &str) -> String {
    compute_line_hash_impl(idx, line)
}

#[pyfunction]
#[pyo3(signature = (text, start_line=1))]
fn format_hashlines(text: &str, start_line: u32) -> String {
    format_hashlines_impl(text, start_line)
}

#[pyfunction]
fn strip_hashline_prefixes(text: &str) -> String {
    strip_hashline_prefixes_impl(text)
}

#[pyfunction]
fn validate_hashline_anchor(idx: u32, line: &str, expected_hash: &str) -> bool {
    validate_hashline_anchor_impl(idx, line, expected_hash)
}

#[pyfunction]
#[pyo3(signature = (messages,))]
fn collect_tool_call_ids(messages: &Bound<'_, PyList>) -> PyResult<(Py<PyAny>, Py<PyAny>)> {
    let (call_set, return_set) = collect_tool_call_ids_impl(messages)?;
    Ok((call_set.into_any(), return_set.into_any()))
}

#[pymodule]
fn _code_puppy_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<ProcessResult>()?;
    m.add_class::<PruneResult>()?;
    m.add_class::<SplitResult>()?;
    m.add_function(wrap_pyfunction!(process_messages_batch, m)?)?;
    m.add_function(wrap_pyfunction!(prune_and_filter, m)?)?;
    m.add_function(wrap_pyfunction!(truncation_indices, m)?)?;
    m.add_function(wrap_pyfunction!(split_for_summarization, m)?)?;
    m.add_function(wrap_pyfunction!(serialize_session, m)?)?;
    m.add_function(wrap_pyfunction!(deserialize_session, m)?)?;
    m.add_function(wrap_pyfunction!(serialize_session_incremental, m)?)?;
    m.add_function(wrap_pyfunction!(serialize_messages_incremental, m)?)?;
    m.add_function(wrap_pyfunction!(serialize_session_incremental_new, m)?)?;
    m.add_function(wrap_pyfunction!(get_incremental_message_count, m)?)?;
    m.add_function(wrap_pyfunction!(get_incremental_data_offset, m)?)?;
    m.add_function(wrap_pyfunction!(get_compacted_hashes_offset, m)?)?;
    m.add_function(wrap_pyfunction!(append_messages_incremental, m)?)?;
    m.add_function(wrap_pyfunction!(deserialize_incremental_with_hashes, m)?)?;
    m.add_function(wrap_pyfunction!(collect_tool_call_ids, m)?)?;
    m.add_function(wrap_pyfunction!(compute_line_hash, m)?)?;
    m.add_function(wrap_pyfunction!(format_hashlines, m)?)?;
    m.add_function(wrap_pyfunction!(strip_hashline_prefixes, m)?)?;
    m.add_function(wrap_pyfunction!(validate_hashline_anchor, m)?)?;
    Ok(())
}
