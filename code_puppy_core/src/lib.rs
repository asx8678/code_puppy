use pyo3::prelude::*;
use pyo3::types::PyList;

mod message_hashing;
mod pruning;

mod serialization;
mod token_estimation;
mod types;
use pruning::{
    prune_and_filter_core, prune_and_filter_impl,
    split_for_summarization_core, split_for_summarization_impl, truncation_indices_impl,
};
use serialization::{
    deserialize_session_impl, serialize_session_impl, serialize_session_incremental_impl,
};
use token_estimation::process_messages_batch_core;
use token_estimation::process_messages_batch_impl;
use types::{Message, ToolDefinition};

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

// ── MessageBatch pyclass ───────────────────────────────────────────────────

use std::sync::Mutex;

#[pyclass(frozen)]
pub struct MessageBatch {
    messages: Vec<Message>,
    /// Cached after first process() call — protected by Mutex for thread-safety
    per_message_tokens: Mutex<Option<Vec<i64>>>,
    total_tokens: Mutex<Option<i64>>,
    message_hashes: Mutex<Option<Vec<i64>>>,
    context_overhead_tokens: Mutex<Option<i64>>,
}

#[pymethods]
impl MessageBatch {
    /// Create batch from Python list of message dicts (serialized format)
    #[new]
    fn from_py_list(messages: &Bound<'_, PyList>) -> PyResult<Self> {
        let msgs: Vec<Message> = messages
            .iter()
            .map(|o| Message::from_py(&o))
            .collect::<PyResult<_>>()?;

        Ok(MessageBatch {
            messages: msgs,
            per_message_tokens: Mutex::new(None),
            total_tokens: Mutex::new(None),
            message_hashes: Mutex::new(None),
            context_overhead_tokens: Mutex::new(None),
        })
    }

    /// Get number of messages
    fn len(&self) -> usize {
        self.messages.len()
    }

    /// Get whether the batch is empty
    fn is_empty(&self) -> bool {
        self.messages.is_empty()
    }

    /// Process messages and cache token counts (wraps process_messages_batch logic)
    #[pyo3(signature = (tool_definitions, mcp_tool_definitions, system_prompt))]
    fn process(
        &self,
        tool_definitions: &Bound<'_, PyList>,
        mcp_tool_definitions: &Bound<'_, PyList>,
        system_prompt: &str,
    ) -> PyResult<ProcessResult> {
        let tool_defs: Vec<ToolDefinition> = tool_definitions
            .iter()
            .map(|o| ToolDefinition::from_py(&o))
            .collect::<PyResult<_>>()?;
        let mcp_defs: Vec<ToolDefinition> = mcp_tool_definitions
            .iter()
            .map(|o| ToolDefinition::from_py(&o))
            .collect::<PyResult<_>>()?;

        let (per_message_tokens, total_message_tokens, context_overhead, message_hashes) =
            process_messages_batch_core(
                &self.messages,
                &tool_defs,
                &mcp_defs,
                system_prompt,
            );

        // Cache the results (thread-safe via Mutex)
        *self.per_message_tokens.lock().unwrap() = Some(per_message_tokens.clone());
        *self.total_tokens.lock().unwrap() = Some(total_message_tokens);
        *self.message_hashes.lock().unwrap() = Some(message_hashes.clone());
        *self.context_overhead_tokens.lock().unwrap() = Some(context_overhead);

        Ok(ProcessResult {
            per_message_tokens,
            total_message_tokens,
            context_overhead_tokens: context_overhead,
            message_hashes,
        })
    }

    /// Prune and filter using cached messages (wraps prune_and_filter logic)
    #[pyo3(signature = (max_tokens_per_message = 50000))]
    fn prune_and_filter(&self, max_tokens_per_message: i64) -> PyResult<PruneResult> {
        Ok(prune_and_filter_core(&self.messages, max_tokens_per_message))
    }

    /// Get truncation indices using cached token counts
    #[pyo3(signature = (protected_tokens, second_has_thinking = false))]
    fn truncation_indices(
        &self,
        protected_tokens: i64,
        second_has_thinking: bool,
    ) -> PyResult<Vec<usize>> {
        let per_message_tokens = self
            .per_message_tokens
            .lock()
            .unwrap()
            .clone()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err(
                "process() must be called before truncation_indices()"
            ))?;

        Ok(truncation_indices_impl(
            &per_message_tokens,
            protected_tokens,
            second_has_thinking,
        ))
    }

    /// Split for summarization using cached data
    fn split_for_summarization(&self, protected_tokens_limit: i64) -> PyResult<SplitResult> {
        let per_message_tokens = self
            .per_message_tokens
            .lock()
            .unwrap()
            .clone()
            .ok_or_else(|| pyo3::exceptions::PyRuntimeError::new_err(
                "process() must be called before split_for_summarization()"
            ))?;

        Ok(split_for_summarization_core(
            &per_message_tokens,
            &self.messages,
            protected_tokens_limit,
        ))
    }

    /// Get cached per-message tokens (None if process() not called yet)
    fn get_per_message_tokens(&self) -> Option<Vec<i64>> {
        self.per_message_tokens.lock().unwrap().clone()
    }

    /// Get cached total tokens (None if process() not called yet)
    fn get_total_tokens(&self) -> Option<i64> {
        *self.total_tokens.lock().unwrap()
    }

    /// Get cached message hashes (None if process() not called yet)
    fn get_message_hashes(&self) -> Option<Vec<i64>> {
        self.message_hashes.lock().unwrap().clone()
    }

    /// Get cached context overhead tokens (None if process() not called yet)
    fn get_context_overhead_tokens(&self) -> Option<i64> {
        *self.context_overhead_tokens.lock().unwrap()
    }
}

// ── Module registration ─────────────────────────────────────────────────────

#[cfg_attr(Py_GIL_DISABLED, pymodule(gil_used = false))]
#[cfg_attr(not(Py_GIL_DISABLED), pymodule)]
fn _code_puppy_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<ProcessResult>()?;
    m.add_class::<PruneResult>()?;
    m.add_class::<SplitResult>()?;
    m.add_class::<MessageBatch>()?;
    m.add_function(wrap_pyfunction!(process_messages_batch, m)?)?;
    m.add_function(wrap_pyfunction!(prune_and_filter, m)?)?;
    m.add_function(wrap_pyfunction!(truncation_indices, m)?)?;
    m.add_function(wrap_pyfunction!(split_for_summarization, m)?)?;
    m.add_function(wrap_pyfunction!(serialize_session, m)?)?;
    m.add_function(wrap_pyfunction!(deserialize_session, m)?)?;
    m.add_function(wrap_pyfunction!(serialize_session_incremental, m)?)?;
    Ok(())
}
