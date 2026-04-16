//! MessagePack-based session serialization.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use crate::types::Message;

pub fn serialize_session_impl(messages: &Bound<'_, PyList>) -> PyResult<Vec<u8>> {
    let msgs: Vec<Message> = messages
        .iter()
        .map(|o| Message::from_py(&o))
        .collect::<PyResult<_>>()?;
    rmp_serde::to_vec(&msgs).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("MessagePack serialization failed: {e}"))
    })
}

pub fn deserialize_session_impl(py: Python<'_>, data: &[u8]) -> PyResult<Py<PyList>> {
    let msgs: Vec<Message> = rmp_serde::from_slice(data).map_err(|e| {
        pyo3::exceptions::PyValueError::new_err(format!("MessagePack deserialization failed: {e}"))
    })?;
    let list = PyList::empty(py);
    for msg in &msgs {
        list.append(message_to_py_dict(py, msg)?)?;
    }
    Ok(list.unbind())
}

pub fn serialize_session_incremental_impl(
    new_messages: &Bound<'_, PyList>,
    existing_data: Option<&[u8]>,
) -> PyResult<Vec<u8>> {
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
