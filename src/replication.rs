use pyo3::prelude::*;
use pyo3::types::{PyDict, PyAny};
use tokio_postgres::NoTls;
use std::sync::Arc;
use tokio::sync::Mutex;
use futures::StreamExt;

use crate::pgoutput::{PgOutputDecoder, PgOutputMessage, ReplicationMessage};
use crate::utils::{build_connection_string, ExponentialBackoff, to_py_err};

use pgwire_replication::{ReplicationClient, ReplicationConfig as PgReplicationConfig, ReplicationEvent, Lsn, TlsConfig};

/// PostgreSQL logical replication reader
#[pyclass]
pub struct LogicalReplicationReader {
    config: ReplicationConfig,
    state: Arc<Mutex<ReaderState>>,
}

#[derive(Clone)]
struct ReplicationConfig {
    publication_name: String,
    slot_name: String,
    host: String,
    database: String,
    port: u16,
    user: String,
    password: String,
    start_lsn: Option<String>,
    auto_acknowledge: bool,
}

struct ReaderState {
    decoder: PgOutputDecoder,
    client: Option<ReplicationClient>,
    stopped: bool,
    current_lsn: Option<u64>,
    pending_lsn: Option<Lsn>,
}

#[pymethods]
impl LogicalReplicationReader {
    #[new]
    #[pyo3(signature = (publication_name, slot_name, host, database, port=5432, user="postgres", password="", start_lsn=None, auto_acknowledge=true))]
    fn new(
        publication_name: String,
        slot_name: String,
        host: String,
        database: String,
        port: u16,
        user: &str,
        password: &str,
        start_lsn: Option<String>,
        auto_acknowledge: bool,
    ) -> Self {
        let config = ReplicationConfig {
            publication_name,
            slot_name,
            host,
            database,
            port,
            user: user.to_string(),
            password: password.to_string(),
            start_lsn,
            auto_acknowledge,
        };
        
        let state = ReaderState {
            decoder: PgOutputDecoder::new(),
            client: None,
            stopped: false,
            current_lsn: None,
            pending_lsn: None,
        };
        
        Self {
            config,
            state: Arc::new(Mutex::new(state)),
        }
    }
    
    fn __aiter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }
    
    fn __anext__<'a>(&'a self, py: Python<'a>) -> PyResult<Option<&'a PyAny>> {
        let state = self.state.clone();
        let config = self.config.clone();
        
        Ok(Some(pyo3_asyncio::tokio::future_into_py(py, async move {
            // Initialize connection if needed
            {
                let mut state_guard = state.lock().await;
                if state_guard.client.is_none() && !state_guard.stopped {
                    // Create replication client
                    let start_lsn = if let Some(lsn_str) = &config.start_lsn {
                        Lsn::parse(lsn_str).unwrap_or(Lsn::ZERO)
                    } else {
                        Lsn::ZERO
                    };
                    
                    let repl_config = PgReplicationConfig {
                        host: config.host.clone(),  
                        port: config.port,
                        user: config.user.clone(),
                        password: config.password.clone(),
                        database: config.database.clone(),
                        slot: config.slot_name.clone(),
                        publication: config.publication_name.clone(),
                        start_lsn,
                        stop_at_lsn: None,
                        tls: TlsConfig::disabled(),
                        status_interval: std::time::Duration::from_secs(10),
                        idle_wakeup_interval: std::time::Duration::from_secs(10),
                        buffer_events: 8192,
                    };
                    
                    let client = ReplicationClient::connect(repl_config)
                        .await
                        .map_err(|e| to_py_err(format!("Connection failed: {}", e)))?;
                    
                    state_guard.client = Some(client);
                }
            }
            
            // Get next event and convert to message
            loop {
                // Take client temporarily out of state to call recv() without holding lock
                let mut client_opt = {
                    let mut state_guard = state.lock().await;
                    if state_guard.stopped {
                        return Ok(None);
                    }
                    state_guard.client.take()
                };
                
                let mut client = match client_opt {
                    Some(c) => c,
                    None => return Ok(None),
                };
                
                // Call recv() without holding the lock
                let event_result = client.recv().await;
                
                // Now process the event with access to state
                match event_result {
                    Ok(Some(event)) => {
                        match event {
                            ReplicationEvent::XLogData { data, wal_end, .. } => {
                                // Get decoder and decode
                                let (decoded_msg, should_return_msg) = {
                                    let mut state_guard = state.lock().await;
                                    
                                    match state_guard.decoder.decode(data) {
                                        Ok(pg_msg) => {
                                            // Update LSN based on auto_acknowledge setting
                                            if config.auto_acknowledge {
                                                client.update_applied_lsn(wal_end);
                                            } else {
                                                // Store pending LSN for manual acknowledgment
                                                state_guard.pending_lsn = Some(wal_end);
                                            }
                                            
                                            // Convert to ReplicationMessage
                                            let lsn_u64 = wal_end.into();
                                            let repl_msg = Python::with_gil(|py| {
                                                Self::convert_message(py, &pg_msg, &state_guard.decoder, lsn_u64, &config)
                                            });
                                            
                                            // Put client back
                                            state_guard.client = Some(client);
                                            
                                            (Ok(()), repl_msg)
                                        }
                                        Err(e) => {
                                            eprintln!("Failed to decode pgoutput message: {}", e);
                                            // Put client back
                                            state_guard.client = Some(client);
                                            (Err(()), None)
                                        }
                                    }
                                };
                                
                                if let Ok(()) = decoded_msg {
                                    if let Some(msg) = should_return_msg {
                                        return Ok(Some(msg));
                                    }
                                }
                                // Continue loop for other events
                            }
                            _ => {
                                // For other events, just put client back and continue
                                let mut state_guard = state.lock().await;
                                state_guard.client = Some(client);
                                
                                if matches!(event, ReplicationEvent::StoppedAt { .. }) {
                                    return Ok(None);
                                }
                                // Continue loop
                            }
                        }
                    }
                    Ok(None) => {
                        // Put client back
                        let mut state_guard = state.lock().await;
                        state_guard.client = Some(client);
                        return Ok(None);
                    }
                    Err(e) => {
                        // Put client back
                        let mut state_guard = state.lock().await;
                        state_guard.client = Some(client);
                        return Err(to_py_err(format!("Replication error: {}", e)));
                    }
                }
            }
        })?))
    }
    
    fn stop<'a>(&'a self, py: Python<'a>) -> PyResult<&'a PyAny> {
        let state = self.state.clone();
        
        pyo3_asyncio::tokio::future_into_py(py, async move {
            let mut state_guard = state.lock().await;
            state_guard.stopped = true;
            state_guard.client = None;  // Drop the client
            
            Ok(())
        })
    }
    
    /// Manually acknowledge processing up to the specified or pending LSN.
    /// Only needed when auto_acknowledge=False.
    #[pyo3(signature = (lsn=None))]
    fn acknowledge<'py>(&'py self, py: Python<'py>, lsn: Option<String>) -> PyResult<&'py PyAny> {
        let state = self.state.clone();
        
        pyo3_asyncio::tokio::future_into_py(py, async move {
            let mut state_guard = state.lock().await;
            
            // Take client temporarily
            let client = state_guard.client.take()
                .ok_or_else(|| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                    "Client not available - may be in use by read_message()"
                ))?;
            
            // Determine which LSN to acknowledge
            let lsn_to_ack = if let Some(lsn_str) = lsn {
                // Parse provided LSN string
                let lsn_u64 = lsn_str.parse::<u64>()
                    .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(
                        format!("Invalid LSN format: {}", e)
                    ))?;
                Lsn::from(lsn_u64)
            } else {
                // Use pending LSN
                state_guard.pending_lsn
                    .ok_or_else(|| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(
                        "No pending LSN to acknowledge"
                    ))?
            };
            
            // Update applied LSN
            let mut client = client;
            client.update_applied_lsn(lsn_to_ack);
            
            // Clear pending LSN
            state_guard.pending_lsn = None;
            
            // Put client back
            state_guard.client = Some(client);
            
            Ok(())
        })
    }
}

impl LogicalReplicationReader {
    #[allow(dead_code)]
    fn convert_message(
        py: Python,
        msg: &PgOutputMessage,
        decoder: &PgOutputDecoder,
        lsn: u64,
        config: &ReplicationConfig,
    ) -> Option<ReplicationMessage> {
        use std::time::{SystemTime, UNIX_EPOCH};
        
        // Get current timestamp
        let now = SystemTime::now().duration_since(UNIX_EPOCH).ok()?;
        let ts_ms = now.as_millis() as i64;
        let ts_us = now.as_micros() as i64;
        let ts_ns = now.as_nanos() as i64;
        
        // Helper to create source metadata (Debezium format)
        fn create_source_metadata(
            py: Python,
            lsn: u64,
            ts_ms: i64,
            database: &str,
            schema: &str,
            table: &str,
            is_snapshot: bool,
        ) -> PyObject {
            let source = PyDict::new(py);
            source.set_item("version", "0.1.0").ok();
            source.set_item("connector", "pgoutput-decoder").ok();
            source.set_item("name", "pgoutput-decoder").ok();
            source.set_item("ts_ms", ts_ms).ok();
            source.set_item("snapshot", if is_snapshot { "true" } else { "false" }).ok();
            source.set_item("db", database).ok();
            source.set_item("schema", schema).ok();
            source.set_item("table", table).ok();
            source.set_item("lsn", lsn).ok();
            source.into()
        }
        
        match msg {
            PgOutputMessage::Begin(_) => None,
            PgOutputMessage::Commit(_) => None,
            PgOutputMessage::Relation(_) => None,
            
            PgOutputMessage::Insert(insert) => {
                if let Some(relation) = decoder.get_relation(insert.rel_id) {
                    // Build "after" data
                    let after_dict = PyDict::new(py);
                    for (i, col_value) in insert.tuple.iter().enumerate() {
                        if let Some(col_info) = relation.columns.get(i) {
                            let py_value = crate::pgoutput::convert_pg_value(
                                py,
                                col_value.as_ref().map(|v| v.as_slice()),
                                col_info.type_id,
                            ).ok()?;
                            after_dict.set_item(&col_info.name, py_value).ok()?;
                        }
                    }
                    
                    let source = create_source_metadata(
                        py,
                        lsn,
                        ts_ms,
                        &config.database,
                        &relation.namespace,
                        &relation.name,
                        false,
                    );
                    
                    Some(ReplicationMessage {
                        before: None,
                        after: Some(after_dict.into()),
                        source,
                        op: "c".to_string(),
                        ts_ms,
                        ts_us: Some(ts_us),
                        ts_ns: Some(ts_ns),
                    })
                } else {
                    None
                }
            }
            
            PgOutputMessage::Update(update) => {
                if let Some(relation) = decoder.get_relation(update.rel_id) {
                    // Build "before" data (if available)
                    let before = if let Some(old_tuple) = &update.old_tuple {
                        let before_dict = PyDict::new(py);
                        for (i, col_value) in old_tuple.iter().enumerate() {
                            if let Some(col_info) = relation.columns.get(i) {
                                let py_value = crate::pgoutput::convert_pg_value(
                                    py,
                                    col_value.as_ref().map(|v| v.as_slice()),
                                    col_info.type_id,
                                ).ok()?;
                                before_dict.set_item(&col_info.name, py_value).ok()?;
                            }
                        }
                        Some(before_dict.into())
                    } else {
                        None
                    };
                    
                    // Build "after" data
                    let after_dict = PyDict::new(py);
                    for (i, col_value) in update.new_tuple.iter().enumerate() {
                        if let Some(col_info) = relation.columns.get(i) {
                            let py_value = crate::pgoutput::convert_pg_value(
                                py,
                                col_value.as_ref().map(|v| v.as_slice()),
                                col_info.type_id,
                            ).ok()?;
                            after_dict.set_item(&col_info.name, py_value).ok()?;
                        }
                    }
                    
                    let source = create_source_metadata(
                        py,
                        lsn,
                        ts_ms,
                        &config.database,
                        &relation.namespace,
                        &relation.name,
                        false,
                    );
                    
                    Some(ReplicationMessage {
                        before,
                        after: Some(after_dict.into()),
                        source,
                        op: "u".to_string(),
                        ts_ms,
                        ts_us: Some(ts_us),
                        ts_ns: Some(ts_ns),
                    })
                } else {
                    None
                }
            }
            
            PgOutputMessage::Delete(delete) => {
                if let Some(relation) = decoder.get_relation(delete.rel_id) {
                    // Build "before" data
                    let before_dict = PyDict::new(py);
                    for (i, col_value) in delete.old_tuple.iter().enumerate() {
                        if let Some(col_info) = relation.columns.get(i) {
                            let py_value = crate::pgoutput::convert_pg_value(
                                py,
                                col_value.as_ref().map(|v| v.as_slice()),
                                col_info.type_id,
                            ).ok()?;
                            before_dict.set_item(&col_info.name, py_value).ok()?;
                        }
                    }
                    
                    let source = create_source_metadata(
                        py,
                        lsn,
                        ts_ms,
                        &config.database,
                        &relation.namespace,
                        &relation.name,
                        false,
                    );
                    
                    Some(ReplicationMessage {
                        before: Some(before_dict.into()),
                        after: None,
                        source,
                        op: "d".to_string(),
                        ts_ms,
                        ts_us: Some(ts_us),
                        ts_ns: Some(ts_ns),
                    })
                } else {
                    None
                }
            }
            
            _ => None,
        }
    }
}
