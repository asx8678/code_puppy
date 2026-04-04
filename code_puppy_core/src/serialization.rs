//! MessagePack-based session serialization with incremental support.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use crate::types::Message;

// Magic header for incremental format (different from old msgpack format)
const INCREMENTAL_MAGIC: &[u8] = b"CPINCV01";

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
            
            return serialize_session_incremental_new_impl(&combined, None);
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

/// Get the byte offset where the compacted_hashes section begins.
/// This is after all messages (we need to scan through them).
pub fn get_compacted_hashes_offset_impl(data: &[u8]) -> PyResult<usize> {
    if !data.starts_with(INCREMENTAL_MAGIC) {
        return Err(pyerr("Not an incremental format file"));
    }
    
    let count = get_incremental_message_count_impl(data)?;
    let header_end = INCREMENTAL_MAGIC.len() + 6;
    
    let mut offset = header_end;
    for _ in 0..count {
        if data.len() < offset + 4 {
            return Err(pyerr("File truncated reading message length"));
        }
        let msg_len = u32::from_le_bytes([
            data[offset], data[offset+1], data[offset+2], data[offset+3]
        ]) as usize;
        offset += 4 + msg_len;
    }
    
    Ok(offset)
}

/// Append new messages to an existing incremental file.
/// Returns the new file data with updated header and appended messages.
/// Preserves existing compacted_hashes.
pub fn append_messages_incremental_impl(
    existing_data: &[u8],
    new_messages: &Bound<'_, PyList>,
) -> PyResult<Vec<u8>> {
    if !existing_data.starts_with(INCREMENTAL_MAGIC) {
        return Err(pyerr("Not an incremental format file"));
    }
    
    let existing_count = get_incremental_message_count_impl(existing_data)?;
    let new_count = new_messages.len();
    let total_count = existing_count + new_count as usize;
    
    // Find where compacted_hashes section begins (end of messages)
    let hashes_offset = get_compacted_hashes_offset_impl(existing_data)?;
    
    // Extract existing compacted_hashes if present
    let existing_hashes: Vec<String> = if hashes_offset < existing_data.len() {
        // Read compacted_hashes length and data
        if existing_data.len() >= hashes_offset + 4 {
            let hashes_len = u32::from_le_bytes([
                existing_data[hashes_offset],
                existing_data[hashes_offset+1],
                existing_data[hashes_offset+2],
                existing_data[hashes_offset+3],
            ]) as usize;
            if existing_data.len() >= hashes_offset + 4 + hashes_len {
                rmp_serde::from_slice(&existing_data[hashes_offset+4..hashes_offset+4+hashes_len])
                    .map_err(|e| pyerr(&format!("Failed to deserialize hashes: {e}")))?
            } else {
                Vec::new()
            }
        } else {
            Vec::new()
        }
    } else {
        Vec::new()
    };
    
    // Serialize new messages
    let new_msgs_serialized = serialize_messages_incremental_impl(new_messages)?;
    
    // Build new file:
    // 1. Header with updated count
    // 2. Existing messages (from original file, up to hashes_offset)
    // 3. New messages
    // 4. Compacted hashes section
    
    let mut result = Vec::new();
    
    // Magic
    result.extend_from_slice(INCREMENTAL_MAGIC);
    
    // Header: version (1), flags (1), message_count (4 LE)
    result.push(1u8); // version
    result.push(0u8); // flags (reserved)
    let count_bytes = (total_count as u32).to_le_bytes();
    result.extend_from_slice(&count_bytes);
    
    // Existing messages (from header end to hashes_offset)
    let header_end = INCREMENTAL_MAGIC.len() + 6;
    result.extend_from_slice(&existing_data[header_end..hashes_offset]);
    
    // New messages
    result.extend_from_slice(&new_msgs_serialized);
    
    // Compacted hashes section
    let hashes_bytes = rmp_serde::to_vec(&existing_hashes).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("Failed to serialize hashes: {e}"))
    })?;
    let hashes_len_bytes = (hashes_bytes.len() as u32).to_le_bytes();
    result.extend_from_slice(&hashes_len_bytes);
    result.extend_from_slice(&hashes_bytes);
    
    Ok(result)
}

/// Deserialize incremental format including compacted_hashes.
/// Returns (messages, compacted_hashes) tuple.
pub fn deserialize_incremental_with_hashes_impl<'py>(
    py: Python<'py>,
    data: &[u8],
) -> PyResult<(Py<PyList>, Vec<String>)> {
    if !data.starts_with(INCREMENTAL_MAGIC) {
        return Err(pyerr("Not an incremental format file"));
    }
    
    let count = get_incremental_message_count_impl(data)?;
    let header_end = INCREMENTAL_MAGIC.len() + 6;
    let mut offset = header_end;
    
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
    
    // Read compacted_hashes if present
    let hashes: Vec<String> = if data.len() > offset + 4 {
        let hashes_len = u32::from_le_bytes([
            data[offset], data[offset+1], data[offset+2], data[offset+3],
        ]) as usize;
        offset += 4;
        if data.len() >= offset + hashes_len {
            rmp_serde::from_slice(&data[offset..offset+hashes_len])
                .map_err(|e| pyerr(&format!("Failed to deserialize hashes: {e}")))?
        } else {
            Vec::new()
        }
    } else {
        Vec::new()
    };
    
    Ok((list.unbind(), hashes))
}

/// Create a new incremental format file with compacted_hashes support.
pub fn serialize_session_incremental_new_impl(
    messages: &Bound<'_, PyList>,
    compacted_hashes: Option<&Bound<'_, PyList>>,
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
    
    // Write compacted_hashes
    let hashes: Vec<String> = if let Some(hashes_list) = compacted_hashes {
        hashes_list.iter()
            .map(|o| o.extract::<String>())
            .collect::<PyResult<_>>()?
    } else {
        Vec::new()
    };
    
    let hashes_bytes = rmp_serde::to_vec(&hashes).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("Hashes serialization failed: {e}"))
    })?;
    let hashes_len_bytes = (hashes_bytes.len() as u32).to_le_bytes();
    result.extend_from_slice(&hashes_len_bytes);
    result.extend_from_slice(&hashes_bytes);
    
    Ok(result)
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
