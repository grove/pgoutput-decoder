use pyo3::prelude::*;
use std::collections::HashMap;
use serde_json::ser::PrettyFormatter;
use serde::Serialize;

/// Represents a decoded replication message in Debezium format
#[derive(Debug, Clone)]
#[pyclass]
pub struct ReplicationMessage {
    /// State of the row before the event (for UPDATE and DELETE)
    #[pyo3(get)]
    pub before: Option<PyObject>,
    
    /// State of the row after the event (for INSERT and UPDATE)
    #[pyo3(get)]
    pub after: Option<PyObject>,
    
    /// Source metadata
    #[pyo3(get)]
    pub source: PyObject,
    
    /// Operation type: "c" (create), "u" (update), "d" (delete), "r" (read/snapshot)
    #[pyo3(get)]
    pub op: String,
    
    /// Timestamp when connector processed the event (milliseconds since epoch)
    #[pyo3(get)]
    pub ts_ms: i64,
    
    /// Timestamp when connector processed the event (microseconds since epoch)
    #[pyo3(get)]
    pub ts_us: Option<i64>,
    
    /// Timestamp when connector processed the event (nanoseconds since epoch)
    #[pyo3(get)]
    pub ts_ns: Option<i64>,
}

#[pymethods]
impl ReplicationMessage {
    fn json(&self, py: Python, indent: Option<usize>) -> PyResult<String> {
        to_debezium_json_impl(py, self, indent)
    }
    
    fn __repr__(&self) -> String {
        format!("ReplicationMessage(op={})", self.op)
    }
}

/// Begin transaction message
#[derive(Debug, Clone)]
pub struct BeginMessage {
    pub final_lsn: u64,
    pub timestamp: i64,
    pub xid: u32,
}

/// Commit transaction message
#[derive(Debug, Clone)]
pub struct CommitMessage {
    pub flags: u8,
    pub commit_lsn: u64,
    pub end_lsn: u64,
    pub timestamp: i64,
}

/// Relation (table schema) message
#[derive(Debug, Clone)]
pub struct RelationMessage {
    pub rel_id: u32,
    pub namespace: String,
    pub name: String,
    pub replica_identity: u8,
    pub columns: Vec<ColumnInfo>,
}

#[derive(Debug, Clone)]
pub struct ColumnInfo {
    pub flags: u8,
    pub name: String,
    pub type_id: u32,
    pub type_modifier: i32,
}

/// Insert message
#[derive(Debug, Clone)]
pub struct InsertMessage {
    pub rel_id: u32,
    pub tuple: Vec<Option<Vec<u8>>>,
}

/// Update message
#[derive(Debug, Clone)]
pub struct UpdateMessage {
    pub rel_id: u32,
    pub old_tuple: Option<Vec<Option<Vec<u8>>>>,
    pub new_tuple: Vec<Option<Vec<u8>>>,
}

/// Delete message
#[derive(Debug, Clone)]
pub struct DeleteMessage {
    pub rel_id: u32,
    pub old_tuple: Vec<Option<Vec<u8>>>,
}

/// Truncate message
#[derive(Debug, Clone)]
pub struct TruncateMessage {
    pub options: u8,
    pub rel_ids: Vec<u32>,
}

/// Type message
#[derive(Debug, Clone)]
pub struct TypeMessage {
    pub type_id: u32,
    pub namespace: String,
    pub name: String,
}

/// Origin message
#[derive(Debug, Clone)]
pub struct OriginMessage {
    pub lsn: u64,
    pub name: String,
}

/// Logical replication message (sent via pg_logical_emit_message)
#[derive(Debug, Clone)]
pub struct LogicalMessage {
    pub transactional: bool,
    pub lsn: u64,
    pub prefix: String,
    pub content: Vec<u8>,
}

/// Enum for all pgoutput message types
#[derive(Debug, Clone)]
pub enum PgOutputMessage {
    Begin(BeginMessage),
    Commit(CommitMessage),
    Relation(RelationMessage),
    Insert(InsertMessage),
    Update(UpdateMessage),
    Delete(DeleteMessage),
    Truncate(TruncateMessage),
    Type(TypeMessage),
    Origin(OriginMessage),
    Message(LogicalMessage),
}

// Helper function to convert PyObject to JSON value
fn py_to_json(py: Python, obj: &PyObject) -> serde_json::Value {
    if obj.is_none(py) {
        return serde_json::Value::Null;
    }
    
    if let Ok(dict) = obj.extract::<HashMap<String, PyObject>>(py) {
        let mut map = serde_json::Map::new();
        for (key, value) in dict {
            map.insert(key, py_to_json(py, &value));
        }
        return serde_json::Value::Object(map);
    }
    
    if let Ok(s) = obj.extract::<String>(py) {
        return serde_json::Value::String(s);
    }
    if let Ok(i) = obj.extract::<i64>(py) {
        return serde_json::Value::Number(i.into());
    }
    if let Ok(f) = obj.extract::<f64>(py) {
        if let Some(num) = serde_json::Number::from_f64(f) {
            return serde_json::Value::Number(num);
        }
    }
    if let Ok(b) = obj.extract::<bool>(py) {
        return serde_json::Value::Bool(b);
    }
    
    serde_json::Value::Null
}

/// Internal implementation for converting ReplicationMessage to Debezium JSON
fn to_debezium_json_impl(py: Python, message: &ReplicationMessage, indent: Option<usize>) -> PyResult<String> {
    let before_json = message.before.as_ref().map(|b| py_to_json(py, b)).unwrap_or(serde_json::Value::Null);
    let after_json = message.after.as_ref().map(|a| py_to_json(py, a)).unwrap_or(serde_json::Value::Null);
    let source_json = py_to_json(py, &message.source);
    
    let mut obj = serde_json::json!({
        "op": message.op,
        "before": before_json,
        "after": after_json,
        "source": source_json,
        "ts_ms": message.ts_ms,
    });
    
    if let Some(ts_us) = message.ts_us {
        obj["ts_us"] = serde_json::json!(ts_us);
    }
    if let Some(ts_ns) = message.ts_ns {
        obj["ts_ns"] = serde_json::json!(ts_ns);
    }
    
    let json_str = if let Some(indent_size) = indent {
        // Create custom formatter with specified indentation
        let indent_bytes = vec![b' '; indent_size];
        let mut buf = Vec::new();
        let mut ser = serde_json::Serializer::with_formatter(
            &mut buf,
            PrettyFormatter::with_indent(&indent_bytes),
        );
        obj.serialize(&mut ser).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("JSON serialization failed: {}", e))
        })?;
        String::from_utf8(buf).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("UTF-8 conversion failed: {}", e))
        })?
    } else {
        // Compact JSON
        serde_json::to_string(&obj).map_err(|e| {
            PyErr::new::<pyo3::exceptions::PyValueError, _>(format!("JSON serialization failed: {}", e))
        })?
    };
    
    Ok(json_str)
}

/// Convert a ReplicationMessage to Debezium-compatible JSON string.
/// 
/// This is a standalone function that can be called from Python as:
/// `message_to_debezium_json(message, indent=2)`
#[pyfunction]
#[pyo3(signature = (message, indent=Some(2)))]
pub fn message_to_debezium_json(py: Python, message: &ReplicationMessage, indent: Option<usize>) -> PyResult<String> {
    to_debezium_json_impl(py, message, indent)
}
