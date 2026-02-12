#![allow(non_local_definitions)] // False positive with PyO3 macros in Rust 1.93+

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;

mod pgoutput;
mod replication;
mod utils;

use pgoutput::{message_to_debezium_json, ReplicationMessage};
use replication::LogicalReplicationReader;

/// PostgreSQL logical replication library with pgoutput decoder
#[pymodule]
fn _pgoutput_decoder(py: Python, m: &PyModule) -> PyResult<()> {
    // Initialize async runtime for pyo3-asyncio
    // Note: pyo3-asyncio 0.20 init takes a Builder, not Python
    // The runtime is initialized automatically when using pyo3_asyncio::tokio::future_into_py

    // Register classes
    m.add_class::<LogicalReplicationReader>()?;
    m.add_class::<ReplicationMessage>()?;

    // Register functions
    m.add_function(wrap_pyfunction!(message_to_debezium_json, m)?)?;

    // Register exceptions
    m.add("ReplicationError", py.get_type::<PyRuntimeError>())?;

    Ok(())
}
