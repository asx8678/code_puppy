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

impl MessagePart {
    /// Extract MessagePart directly from a Python pydantic-ai message part object.
    /// Uses getattr to access attributes directly without intermediate dict creation.
    pub fn from_py_object(part_obj: &Bound<'_, PyAny>) -> PyResult<Self> {
        let part_kind: String = part_obj.getattr("part_kind")?.extract::<String>()?;
        
        let tool_call_id: Option<String> = match part_obj.getattr("tool_call_id") {
            Ok(v) if !v.is_none() => Some(v.extract::<String>()?),
            _ => None,
        };
        
        let tool_name: Option<String> = match part_obj.getattr("tool_name") {
            Ok(v) if !v.is_none() => Some(v.extract::<String>()?),
            _ => None,
        };
        
        // Get args - could be a dict or None
        let args: Option<String> = match part_obj.getattr("args") {
            Ok(v) if !v.is_none() => {
                if let Ok(s) = v.extract::<String>() {
                    Some(s)
                } else {
                    // Try to convert to string representation
                    Some(v.repr()?.to_string())
                }
            }
            _ => None,
        };

        // Handle content - can be str, list, dict, or pydantic model
        let mut content: Option<String> = None;
        let mut content_json: Option<String> = None;
        
        match part_obj.getattr("content") {
            Ok(content_obj) if !content_obj.is_none() => {
                if let Ok(s) = content_obj.extract::<String>() {
                    content = Some(s);
                } else if let Ok(list) = content_obj.cast::<PyList>() {
                    // Handle list content - join text parts
                    let mut text_parts = Vec::new();
                    for item in list.iter() {
                        if let Ok(s) = item.extract::<String>() {
                            text_parts.push(s);
                        }
                        // Skip BinaryContent and other non-string items
                    }
                    if !text_parts.is_empty() {
                        content = Some(text_parts.join("\n"));
                    }
                } else if content_obj.hasattr("model_dump_json")? {
                    // It's a pydantic model - call model_dump_json()
                    let json_str = content_obj.call_method0("model_dump_json")?.extract::<String>()?;
                    content_json = Some(json_str);
                } else if let Ok(_) = content_obj.cast::<PyDict>() {
                    // It's a dict - serialize to JSON
                    let json_str = content_obj.repr()?.to_string();
                    content_json = Some(json_str);
                } else {
                    // Fallback to repr
                    content = Some(content_obj.repr()?.to_string());
                }
            }
            _ => {}
        }

        Ok(MessagePart {
            part_kind,
            content,
            content_json,
            tool_call_id,
            tool_name,
            args,
        })
    }
}

impl Message {
    /// Extract Message from a Python dict (original approach for backward compatibility).
    pub fn from_py(obj: &Bound<'_, PyAny>) -> PyResult<Self> {
        // Try to detect if this is a raw pydantic-ai object or a dict
        if obj.hasattr("parts")? {
            // It's a raw pydantic-ai object - use direct access
            return Self::from_py_object(obj);
        }
        
        // Fall back to dict parsing for backward compatibility
        let dict = match obj.cast::<PyDict>() {
            Ok(d) => d,
            Err(_) => {
                // Graceful fallback for non-message, non-dict inputs
                return Ok(Message { kind: String::new(), role: None, instructions: None, parts: vec![] });
            }
        };

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
    
    /// Extract Message directly from a Python pydantic-ai message object.
    /// Uses getattr to access attributes directly without intermediate dict creation.
    pub fn from_py_object(obj: &Bound<'_, PyAny>) -> PyResult<Self> {
        // Determine kind from the type name
        let type_name = obj.get_type().name()?.to_string();
        let kind = if type_name.contains("Request") || type_name.contains("request") {
            "request".to_string()
        } else {
            "response".to_string()
        };
        
        let role: Option<String> = match obj.getattr("role") {
            Ok(v) if !v.is_none() => Some(v.extract::<String>()?),
            _ => None,
        };
        
        let instructions: Option<String> = match obj.getattr("instructions") {
            Ok(v) if !v.is_none() => Some(v.extract::<String>()?),
            _ => None,
        };

        let mut parts = Vec::new();
        
        // Access parts attribute directly
        match obj.getattr("parts") {
            Ok(parts_obj) if !parts_obj.is_none() => {
                if let Ok(parts_list) = parts_obj.cast::<PyList>() {
                    for part_obj in parts_list.iter() {
                        // Try to extract part directly as object first
                        match MessagePart::from_py_object(&part_obj) {
                            Ok(part) => parts.push(part),
                            Err(_) => {
                                // Fallback: try as dict
                                if let Ok(pd) = part_obj.cast::<PyDict>() {
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
                    }
                }
            }
            _ => {}
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
