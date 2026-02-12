use std::time::Duration;
use tokio::time::sleep;
use pyo3::prelude::*;
use pyo3::exceptions::PyRuntimeError;

/// Build a PostgreSQL connection string from parameters
pub fn build_connection_string(
    host: &str,
    database: &str,
    port: u16,
    user: &str,
    password: &str,
) -> String {
    // Use key-value format which is more reliable
    // Quote values that might contain special characters
    // Note: replication mode is established via SQL commands, not connection params
    format!(
        "host='{}' port='{}' dbname='{}' user='{}' password='{}'",
        host.replace("'", "\\'"),
        port,
        database.replace("'", "\\'"),
        user.replace("'", "\\'"),
        password.replace("'", "\\'")
    )
}

/// Exponential backoff implementation for reconnection attempts
pub struct ExponentialBackoff {
    pub current_delay: Duration,
    pub max_delay: Duration,
    pub multiplier: f64,
    pub attempts: u32,
}

impl ExponentialBackoff {
    pub fn new() -> Self {
        Self {
            current_delay: Duration::from_millis(100),
            max_delay: Duration::from_secs(30),
            multiplier: 2.0,
            attempts: 0,
        }
    }
    
    pub async fn wait(&mut self) {
        sleep(self.current_delay).await;
        self.attempts += 1;
        
        let next_delay = self.current_delay.as_millis() as f64 * self.multiplier;
        self.current_delay = Duration::from_millis(next_delay as u64).min(self.max_delay);
    }
    
    pub fn reset(&mut self) {
        self.current_delay = Duration::from_millis(100);
        self.attempts = 0;
    }
}

/// Convert Rust errors to Python exceptions
pub fn to_py_err<E: std::fmt::Display>(error: E) -> PyErr {
    PyRuntimeError::new_err(format!("{}", error))
}
