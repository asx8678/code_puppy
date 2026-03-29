use pyo3::prelude::*;
use pyo3::types::PyList;

mod message_hashing;
mod pruning;
mod serialization;
mod token_estimation;
mod types;

use pruning::{prune_and_filter_impl, split_for_summarization_impl, truncation_indices_impl};
use serialization::{
    deserialize_session_impl, serialize_session_impl, serialize_session_incremental_impl,
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
#[pyo3(signature = (messages, compacted_hashes, max_tokens_per_message=50000))]
fn prune_and_filter(
    messages: &Bound<'_, PyList>,
    compacted_hashes: std::collections::HashSet<i64>,
    max_tokens_per_message: i64,
) -> PyResult<PruneResult> {
    prune_and_filter_impl(messages, compacted_hashes, max_tokens_per_message)
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

// ── Module registration ─────────────────────────────────────────────────────

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
    Ok(())
}
