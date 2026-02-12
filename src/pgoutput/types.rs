use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};
use std::str;

/// Convert PostgreSQL binary/text data to Python objects based on type OID
pub fn convert_pg_value(py: Python, data: Option<&[u8]>, type_id: u32) -> PyResult<PyObject> {
    match data {
        None => Ok(py.None()),
        Some(bytes) => {
            // Convert based on PostgreSQL type OID
            // https://github.com/postgres/postgres/blob/master/src/include/catalog/pg_type.dat
            match type_id {
                16 => convert_bool(py, bytes),          // bool
                20 => convert_int8(py, bytes),          // int8
                21 => convert_int2(py, bytes),          // int2
                23 => convert_int4(py, bytes),          // int4
                25 => convert_text(py, bytes),          // text
                700 => convert_float4(py, bytes),       // float4
                701 => convert_float8(py, bytes),       // float8
                1042 => convert_text(py, bytes),        // char
                1043 => convert_text(py, bytes),        // varchar
                1082 => convert_date(py, bytes),        // date
                1083 => convert_time(py, bytes),        // time
                1114 => convert_timestamp(py, bytes),   // timestamp
                1184 => convert_timestamptz(py, bytes), // timestamptz
                1700 => convert_numeric(py, bytes),     // numeric
                2950 => convert_uuid(py, bytes),        // uuid
                114 => convert_json(py, bytes),         // json
                3802 => convert_json(py, bytes),        // jsonb
                17 => convert_bytea(py, bytes),         // bytea

                // Array types (OID + 1000 typically)
                1000..=1999 => convert_array(py, bytes, type_id),

                // Default: treat as text
                _ => convert_text(py, bytes),
            }
        }
    }
}

fn convert_bool(py: Python, data: &[u8]) -> PyResult<PyObject> {
    let s = str::from_utf8(data).unwrap_or("f");
    Ok((s == "t" || s == "true" || s == "1").into_py(py))
}

fn convert_int2(py: Python, data: &[u8]) -> PyResult<PyObject> {
    let s = str::from_utf8(data).unwrap_or("0");
    Ok(s.parse::<i16>().unwrap_or(0).into_py(py))
}

fn convert_int4(py: Python, data: &[u8]) -> PyResult<PyObject> {
    let s = str::from_utf8(data).unwrap_or("0");
    Ok(s.parse::<i32>().unwrap_or(0).into_py(py))
}

fn convert_int8(py: Python, data: &[u8]) -> PyResult<PyObject> {
    let s = str::from_utf8(data).unwrap_or("0");
    Ok(s.parse::<i64>().unwrap_or(0).into_py(py))
}

fn convert_float4(py: Python, data: &[u8]) -> PyResult<PyObject> {
    let s = str::from_utf8(data).unwrap_or("0.0");
    Ok(s.parse::<f32>().unwrap_or(0.0).into_py(py))
}

fn convert_float8(py: Python, data: &[u8]) -> PyResult<PyObject> {
    let s = str::from_utf8(data).unwrap_or("0.0");
    Ok(s.parse::<f64>().unwrap_or(0.0).into_py(py))
}

fn convert_text(py: Python, data: &[u8]) -> PyResult<PyObject> {
    let s = str::from_utf8(data).unwrap_or("");
    Ok(s.into_py(py))
}

fn convert_numeric(py: Python, data: &[u8]) -> PyResult<PyObject> {
    // Numeric types sent as text in logical replication
    let s = str::from_utf8(data).unwrap_or("0");
    // Try to parse as float for Python
    match s.parse::<f64>() {
        Ok(f) => Ok(f.into_py(py)),
        Err(_) => Ok(s.into_py(py)), // Return as string if can't parse
    }
}

fn convert_date(py: Python, data: &[u8]) -> PyResult<PyObject> {
    let s = str::from_utf8(data).unwrap_or("");
    Ok(s.into_py(py))
}

fn convert_time(py: Python, data: &[u8]) -> PyResult<PyObject> {
    let s = str::from_utf8(data).unwrap_or("");
    Ok(s.into_py(py))
}

fn convert_timestamp(py: Python, data: &[u8]) -> PyResult<PyObject> {
    let s = str::from_utf8(data).unwrap_or("");
    Ok(s.into_py(py))
}

fn convert_timestamptz(py: Python, data: &[u8]) -> PyResult<PyObject> {
    let s = str::from_utf8(data).unwrap_or("");
    Ok(s.into_py(py))
}

fn convert_uuid(py: Python, data: &[u8]) -> PyResult<PyObject> {
    let s = str::from_utf8(data).unwrap_or("");
    Ok(s.into_py(py))
}

fn convert_json(py: Python, data: &[u8]) -> PyResult<PyObject> {
    let s = str::from_utf8(data).unwrap_or("{}");
    // Parse JSON and return as Python dict/list
    match serde_json::from_str::<serde_json::Value>(s) {
        Ok(value) => json_to_py(py, &value),
        Err(_) => Ok(s.into_py(py)), // Return as string if can't parse
    }
}

fn convert_bytea(py: Python, data: &[u8]) -> PyResult<PyObject> {
    // bytea is sent as hex string in text format (\\x prefix)
    let s = str::from_utf8(data).unwrap_or("");
    if let Some(hex_str) = s.strip_prefix("\\x") {
        // Decode hex
        match hex::decode(hex_str) {
            Ok(bytes) => Ok(bytes.into_py(py)),
            Err(_) => Ok(data.into_py(py)),
        }
    } else {
        Ok(data.into_py(py))
    }
}

fn convert_array(py: Python, data: &[u8], _type_id: u32) -> PyResult<PyObject> {
    // PostgreSQL array format: {elem1,elem2,elem3}
    let s = str::from_utf8(data).unwrap_or("{}");

    if s.starts_with('{') && s.ends_with('}') {
        let inner = &s[1..s.len() - 1];
        let elements: Vec<&str> = if inner.is_empty() {
            vec![]
        } else {
            inner.split(',').collect()
        };

        let py_list = PyList::empty(py);
        for elem in elements {
            let trimmed = elem.trim();
            // Handle NULL
            if trimmed == "NULL" {
                py_list.append(py.None())?;
            } else {
                // Remove quotes if present
                let unquoted = if trimmed.starts_with('"') && trimmed.ends_with('"') {
                    &trimmed[1..trimmed.len() - 1]
                } else {
                    trimmed
                };
                py_list.append(unquoted)?;
            }
        }
        Ok(py_list.into())
    } else {
        // Fallback to string
        Ok(s.into_py(py))
    }
}

/// Convert serde_json::Value to Python object
fn json_to_py(py: Python, value: &serde_json::Value) -> PyResult<PyObject> {
    match value {
        serde_json::Value::Null => Ok(py.None()),
        serde_json::Value::Bool(b) => Ok(b.into_py(py)),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(i.into_py(py))
            } else if let Some(f) = n.as_f64() {
                Ok(f.into_py(py))
            } else {
                Ok(n.to_string().into_py(py))
            }
        }
        serde_json::Value::String(s) => Ok(s.into_py(py)),
        serde_json::Value::Array(arr) => {
            let py_list = PyList::empty(py);
            for item in arr {
                py_list.append(json_to_py(py, item)?)?;
            }
            Ok(py_list.into())
        }
        serde_json::Value::Object(obj) => {
            let py_dict = PyDict::new(py);
            for (key, val) in obj {
                py_dict.set_item(key, json_to_py(py, val)?)?;
            }
            Ok(py_dict.into())
        }
    }
}
