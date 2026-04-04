//! MessagePack-based session serialization with incremental support.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::io::Write;

use crate::types::Message;

// Magic header for incremental format (different from old msgpack format)
const INCREMENTAL_MAGIC: &[u8] = b"CPINCV01";
const OLD_MSGPACK_MAGIC: &[u8] = b"MSGPACK\x01";

/// Serialize all messages to a single msgpack array (legacy full-serialization).
pub fn serialize_session_impl(messages: &Bound<'_, PyList>) -> PyResult<Vec<u8>> {
    let msgs: Vec<Message> = messages
        .iter()
        .map(|o| Message::from_py(&o))
        .collect::<PyResult<_>>()?;
    rmp_serde::to_vec(&msgs).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("MessagePack serialization failed: {e}"))
    })
}

/// Deserialize a msgpack array of messages.
pub fn deserialize_session_impl(py: Python<'_>, data: &[u8]) -> PyResult<Py<PyList>> {
    // Check for incremental format and handle it
    if data.starts_with(INCREMENTAL_MAGIC) {
        return deserialize_incremental_impl(py, data);
    }
    
    // Regular msgpack deserialization (handles old format and plain msgpack)
    let msgs: Vec<Message> = rmp_serde::from_slice(data).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("MessagePack deserialization failed: {e}"))
    })?;
    let list = PyList::empty(py);
    for msg in &msgs {
        list.append(message_to_py_dict(py, msg)?)?;
    }
    Ok(list.unbind())
}

/// Incremental format:
/// - Magic: "CPINCV01" (8 bytes)
/// - Header: version (1 byte), flags (1 byte), message_count (4 bytes LE)
/// - Messages: each message is [length (4 bytes LE)][msgpack bytes]
/// 
/// This format allows appending new messages without re-reading existing ones.

/// Serialize only new messages in incremental format.
/// Returns bytes that can be appended to an existing incremental file.
pub fn serialize_messages_incremental_impl(
    new_messages: &Bound<'_, PyList>,
) -> PyResult<Vec<u8>> {
    let new: Vec<Message> = new_messages
        .iter()
        .map(|o| Message::from_py(&o))
        .collect::<PyResult<_>>()?;
    
    let mut result = Vec::new();
    
    for msg in new {
        let msg_bytes = rmp_serde::to_vec(&msg).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("Message serialization failed: {e}"))
        })?;
        
        // Write length prefix (4 bytes, little-endian)
        let len_bytes = (msg_bytes.len() as u32).to_le_bytes();
        result.extend_from_slice(&len_bytes);
        // Write message bytes
        result.extend_from_slice(&msg_bytes);
    }
    
    Ok(result)
}

/// Create a new incremental format file with initial messages.
/// Format: MAGIC + header + [length-prefixed messages]
pub fn serialize_session_incremental_new_impl(
    messages: &Bound<'_, PyList>,
) -> PyResult<Vec<u8>> {
    let msgs: Vec<Message> = messages
        .iter()
        .map(|o| Message::from_py(&o))
        .collect::<PyResult<_>>()?;
    
    let mut result = Vec::new();
    
    // Write magic
    result.extend_from_slice(INCREMENTAL_MAGIC);
    
    // Write header: version (1), flags (1), message_count (4 LE)
    result.push(1u8); // version
    result.push(0u8); // flags (reserved)
    let count_bytes = (msgs.len() as u32).to_le_bytes();
    result.extend_from_slice(&count_bytes);
    
    // Write messages with length prefix
    for msg in msgs {
        let msg_bytes = rmp_serde::to_vec(&msg).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("Message serialization failed: {e}"))
        })?;
        
        let len_bytes = (msg_bytes.len() as u32).to_le_bytes();
        result.extend_from_slice(&len_bytes);
        result.extend_from_slice(&msg_bytes);
    }
    
    Ok(result)
}

/// Deserialize incremental format.
fn deserialize_incremental_impl(py: Python<'_>, data: &[u8]) -> PyResult<Py<PyList>> {
    if !data.starts_with(INCREMENTAL_MAGIC) {
        return Err(pyerr("Not an incremental format file"));
    }
    
    let mut offset = INCREMENTAL_MAGIC.len();
    
    // Read header
    if data.len() < offset + 6 {
        return Err(pyerr("Incremental file too short for header"));
    }
    
    let _version = data[offset]; // version byte
    offset += 1;
    let _flags = data[offset]; // flags byte
    offset += 1;
    
    let count = u32::from_le_bytes([
        data[offset], data[offset+1], data[offset+2], data[offset+3]
    ]) as usize;
    offset += 4;
    
    // Read messages
    let list = PyList::empty(py);
    for _ in 0..count {
        if data.len() < offset + 4 {
            return Err(pyerr("Incremental file truncated (reading length)"));
        }
        
        let msg_len = u32::from_le_bytes([
            data[offset], data[offset+1], data[offset+2], data[offset+3]
        ]) as usize;
        offset += 4;
        
        if data.len() < offset + msg_len {
            return Err(pyerr("Incremental file truncated (reading message)"));
        }
        
        let msg: Message = rmp_serde::from_slice(&data[offset..offset+msg_len])
            .map_err(|e| pyerr(&format!("Failed to deserialize message: {e}")))?;
        offset += msg_len;
        
        list.append(message_to_py_dict(py, &msg)?)?;
    }
    
    Ok(list.unbind())
}

/// Legacy incremental implementation - kept for compatibility.
/// This deserializes existing data and re-serializes everything.
pub fn serialize_session_incremental_impl(
    new_messages: &Bound<'_, PyList>,
    existing_data: Option<&[u8]>,
) -> PyResult<Vec<u8>> {
    // Check if existing data is in incremental format
    if let Some(data) = existing_data {
        if data.starts_with(INCREMENTAL_MAGIC) {
            // Deserialize existing, add new, re-serialize in incremental format
            // This is only used when we need to combine old incremental with new messages
            // In practice, Python should append directly for true incremental saves
            let py = new_messages.py();
            let existing_list = deserialize_incremental_impl(py, data)?;
            let existing_bound = existing_list.bind(py);
            
            // Combine existing + new
            let mut all_msgs: Vec<Message> = existing_bound
                .iter()
                .map(|o| Message::from_py(&o))
                .collect::<PyResult<_>>()?;
            
            let new: Vec<Message> = new_messages
                .iter()
                .map(|o| Message::from_py(&o))
                .collect::<PyResult<_>>()?;
            
            all_msgs.extend(new);
            
            // Create combined list and serialize
            let combined = PyList::empty(py);
            for msg in &all_msgs {
                combined.append(message_to_py_dict(py, msg)?)?;
            }
            
            return serialize_session_incremental_new_impl(&combined);
        }
    }
    
    // Fall back to old behavior for non-incremental formats
    let mut all: Vec<Message> = if let Some(data) = existing_data {
        rmp_serde::from_slice(data).map_err(|e| {
            pyo3::exceptions::PyValueError::new_err(format!("Deserialization failed: {e}"))
        })?
    } else {
        Vec::new()
    };
    let new: Vec<Message> = new_messages
        .iter()
        .map(|o| Message::from_py(&o))
        .collect::<PyResult<_>>()?;
    all.extend(new);
    rmp_serde::to_vec(&all)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("Serialization failed: {e}")))
}

/// Get the message count from an incremental format file without full deserialization.
pub fn get_incremental_message_count_impl(data: &[u8]) -> PyResult<usize> {
    if !data.starts_with(INCREMENTAL_MAGIC) {
        return Err(pyerr("Not an incremental format file"));
    }
    
    let offset = INCREMENTAL_MAGIC.len();
    if data.len() < offset + 6 {
        return Err(pyerr("File too short"));
    }
    
    let count = u32::from_le_bytes([
        data[offset+2], data[offset+3], data[offset+4], data[offset+5]
    ]) as usize;
    
    Ok(count)
}

/// Calculate the byte offset after the header where message data begins.
pub fn get_incremental_data_offset_impl(data: &[u8]) -> PyResult<usize> {
    if !data.starts_with(INCREMENTAL_MAGIC) {
        return Err(pyerr("Not an incremental format file"));
    }
    Ok(INCREMENTAL_MAGIC.len() + 6) // magic (8) + version (1) + flags (1) + count (4)
}

fn pyerr(msg: &str) -> PyErr {
    pyo3::exceptions::PyValueError::new_err(msg.to_string())
}

fn message_to_py_dict<'a>(py: Python<'a>, msg: &Message) -> PyResult<Bound<'a, PyDict>> {
    let dict = PyDict::new(py);
    dict.set_item("kind", &msg.kind)?;
    dict.set_item("role", &msg.role)?;
    dict.set_item("instructions", &msg.instructions)?;
    let parts_list = PyList::empty(py);
    for part in &msg.parts {
        let pd = PyDict::new(py);
        pd.set_item("part_kind", &part.part_kind)?;
        pd.set_item("content", &part.content)?;
        pd.set_item("content_json", &part.content_json)?;
        pd.set_item("tool_call_id", &part.tool_call_id)?;
        pd.set_item("tool_name", &part.tool_name)?;
        pd.set_item("args", &part.args)?;
        parts_list.append(pd)?;
    }
    dict.set_item("parts", parts_list)?;
    Ok(dict)
}

#[cfg(test)]
mod tests {
    use crate::types::{Message, MessagePart};
    #[test]
    fn test_roundtrip_msgpack() {
        let msg = Message {
            kind: "request".into(),
            role: Some("user".into()),
            instructions: None,
            parts: vec![MessagePart {
                part_kind: "text".into(),
                content: Some("hello".into()),
                content_json: None,
                tool_call_id: None,
                tool_name: None,
                args: None,
            }],
        };
        let data = rmp_serde::to_vec(&vec![msg]).unwrap();
        let restored: Vec<Message> = rmp_serde::from_slice(&data).unwrap();
        assert_eq!(restored[0].parts[0].content.as_deref(), Some("hello"));
    }
}
