//! Shared data types for message processing.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MessagePart {
    pub part_kind: String,
    pub content: Option<String>,
    pub content_json: Option<String>,
    pub tool_call_id: Option<String>,
    pub tool_name: Option<String>,
    pub args: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    pub kind: String,
    pub role: Option<String>,
    pub instructions: Option<String>,
    pub parts: Vec<MessagePart>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolDefinition {
    pub name: String,
    pub description: Option<String>,
    pub input_schema: Option<serde_json::Value>,
}

impl Message {
    pub fn from_py(obj: &Bound<'_, PyAny>) -> PyResult<Self> {
        let dict = obj.cast::<PyDict>()?;

        let kind: String = match dict.get_item("kind")? {
            Some(v) => v.extract::<String>()?,
            None => String::new(),
        };
        let role: Option<String> = match dict.get_item("role")? {
            Some(v) if !v.is_none() => Some(v.extract::<String>()?),
            _ => None,
        };
        let instructions: Option<String> = match dict.get_item("instructions")? {
            Some(v) if !v.is_none() => Some(v.extract::<String>()?),
            _ => None,
        };

        let mut parts = Vec::new();
        if let Some(parts_obj) = dict.get_item("parts")? {
            if !parts_obj.is_none() {
                let parts_list = parts_obj.cast::<PyList>()?;
                for part_obj in parts_list.iter() {
                    let pd = part_obj.cast::<PyDict>()?;
                    parts.push(MessagePart {
                        part_kind: match pd.get_item("part_kind")? {
                            Some(v) if !v.is_none() => v.extract::<String>()?,
                            _ => String::new(),
                        },
                        content: match pd.get_item("content")? {
                            Some(v) if !v.is_none() => Some(v.extract::<String>()?),
                            _ => None,
                        },
                        content_json: match pd.get_item("content_json")? {
                            Some(v) if !v.is_none() => Some(v.extract::<String>()?),
                            _ => None,
                        },
                        tool_call_id: match pd.get_item("tool_call_id")? {
                            Some(v) if !v.is_none() => Some(v.extract::<String>()?),
                            _ => None,
                        },
                        tool_name: match pd.get_item("tool_name")? {
                            Some(v) if !v.is_none() => Some(v.extract::<String>()?),
                            _ => None,
                        },
                        args: match pd.get_item("args")? {
                            Some(v) if !v.is_none() => Some(v.extract::<String>()?),
                            _ => None,
                        },
                    });
                }
            }
        }

        Ok(Message {
            kind,
            role,
            instructions,
            parts,
        })
    }
}

impl ToolDefinition {
    pub fn from_py(obj: &Bound<'_, PyAny>) -> PyResult<Self> {
        let dict = obj.cast::<PyDict>()?;
        let name: String = match dict.get_item("name")? {
            Some(v) => v.extract::<String>()?,
            None => String::new(),
        };
        let description: Option<String> = match dict.get_item("description")? {
            Some(v) if !v.is_none() => Some(v.extract::<String>()?),
            _ => None,
        };
        let input_schema: Option<serde_json::Value> = {
            let schema_val = dict.get_item("inputSchema")?.or(dict.get_item("schema")?);
            match schema_val {
                Some(v) if !v.is_none() => {
                    if let Ok(s) = v.extract::<String>() {
                        serde_json::from_str(&s).ok()
                    } else {
                        None
                    }
                }
                _ => None,
            }
        };

        Ok(ToolDefinition {
            name,
            description,
            input_schema,
        })
    }
}
