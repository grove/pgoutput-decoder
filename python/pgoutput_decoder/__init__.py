"""
PostgreSQL logical replication (CDC) library with high-performance Rust backend.

This library provides a simple Python API for consuming PostgreSQL logical replication
streams using the pgoutput plugin.
"""

import json
from typing import Any, Dict, Optional

from ._pgoutput_decoder import LogicalReplicationReader, ReplicationMessage
from ._pgoutput_decoder import message_to_debezium_json as _rust_message_to_debezium_json

__version__ = "0.1.0"
__all__ = [
    "LogicalReplicationReader",
    "ReplicationMessage",
    "message_to_debezium_json",
    "message_to_dict",
    "format_operation",
    "get_table_name",
]


# Helper functions for working with CDC messages


def message_to_debezium_json(message: ReplicationMessage, indent: Optional[int] = 2) -> str:
    """
    Convert a ReplicationMessage to a JSON-serialized Debezium-compatible format.
    
    This function is implemented in Rust for high performance.
    
    Args:
        message: ReplicationMessage object from pgoutput_decoder
        indent: Number of spaces for JSON indentation (None for compact)
    
    Returns:
        JSON string in Debezium format
    
    Example:
        >>> json_str = message_to_debezium_json(message)
        >>> print(json_str)
        {
          "op": "c",
          "before": null,
          "after": {"id": 1, "name": "Alice"},
          ...
        }
    """
    # Call the Rust implementation
    return _rust_message_to_debezium_json(message, indent)


def message_to_dict(message: ReplicationMessage) -> Dict[str, Any]:
    """
    Convert a ReplicationMessage to a dictionary in Debezium format.
    
    Args:
        message: ReplicationMessage object from pgoutput_decoder
    
    Returns:
        Dictionary in Debezium format
    """
    result = {
        "op": message.op,
        "before": message.before,
        "after": message.after,
        "source": dict(message.source),
        "ts_ms": message.ts_ms,
    }
    
    if hasattr(message, 'ts_us') and message.ts_us is not None:
        result["ts_us"] = message.ts_us
    
    if hasattr(message, 'ts_ns') and message.ts_ns is not None:
        result["ts_ns"] = message.ts_ns
    
    return result


def format_operation(op: str) -> str:
    """
    Convert Debezium operation code to human-readable format.
    
    Args:
        op: Operation code ("c", "u", or "d")
    
    Returns:
        Human-readable operation name
    """
    operations = {
        "c": "INSERT",
        "u": "UPDATE",
        "d": "DELETE",
    }
    return operations.get(op, f"UNKNOWN({op})")


def get_table_name(message: ReplicationMessage) -> str:
    """
    Extract the full table name from a message.
    
    Args:
        message: ReplicationMessage object
    
    Returns:
        Fully qualified table name (schema.table)
    """
    source = message.source
    schema = source.get("schema", "public")
    table = source.get("table", "unknown")
    return f"{schema}.{table}"
