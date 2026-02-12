# pgoutput-decoder

High-performance PostgreSQL logical replication (CDC) library with Rust backend and Python bindings.

## Features

- 🚀 **High Performance**: Core decoding logic implemented in Rust using `tokio-postgres`
- 🔄 **Async/Await**: Full async support with Python's asyncio
- 📊 **Debezium-Compatible**: Messages follow Debezium CDC format with before/after states
- ⚡ **Rust-Powered Serialization**: High-performance JSON serialization with `message_to_debezium_json()`
- 🎯 **Manual LSN Control**: Optional manual acknowledgment for exactly-once processing
- 📋 **Comprehensive Type Support**: Handles all common PostgreSQL types including arrays, JSON, and more
- 🔌 **Simple API**: Clean, pythonic interface for consuming replication streams
- 🛡️ **Auto-Reconnect**: Built-in exponential backoff for connection failures
- 🎯 **pgoutput Plugin**: Uses PostgreSQL's native logical replication output plugin

## Installation

```bash
pip install pgoutput-decoder
```

Or install from source using [maturin](https://github.com/PyO3/maturin):

```bash
# Install maturin and uv
pip install maturin uv

# Build and install
maturin develop
```

## Quick Start

```python
import asyncio
import pgoutput_decoder

async def main():
    # Create replication reader
    cdc_reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="test_pub",
        slot_name="test_slot",
        host="localhost",
        database="mydb",
        port=5432,
        user="postgres",
        password="password",
    )
    
    # Consume replication messages (Debezium-compatible format)
    async for message in cdc_reader:
        if message.op == "c":  # INSERT
            print(f"New row: {message.after}")
        elif message.op == "u":  # UPDATE
            print(f"Updated from {message.before} to {message.after}")
        elif message.op == "d":  # DELETE
            print(f"Deleted row: {message.before}")
        
        # Access source metadata
        print(f"Table: {message.source['schema']}.{message.source['table']}")
        print(f"LSN: {message.source['lsn']}")
    
    # Stop when done
    await cdc_reader.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

## PostgreSQL Setup

Before using this library, you need to configure PostgreSQL for logical replication:

### 1. Configure PostgreSQL

Edit `postgresql.conf`:

```conf
wal_level = logical
max_replication_slots = 4
max_wal_senders = 4
```

Restart PostgreSQL after making these changes.

### 2. Create Publication

```sql
-- Create a publication for specific tables
CREATE PUBLICATION my_pub FOR TABLE users, orders;

-- Or for all tables
CREATE PUBLICATION my_pub FOR ALL TABLES;
```

### 3. Create Replication Slot

```sql
-- Create a logical replication slot using pgoutput
SELECT pg_create_logical_replication_slot('my_slot', 'pgoutput');
```

### 4. Grant Permissions

```sql
-- Grant replication permission to your user
ALTER USER myuser WITH REPLICATION;

-- Grant SELECT on published tables
GRANT SELECT ON ALL TABLES IN SCHEMA public TO myuser;
```

## Message Format

Messages follow the **Debezium-compatible** format with before/after states:

```python
{
  "op": "c",                    # Operation: "c" (create/INSERT), "u" (update), "d" (delete)
  "before": None,               # Previous row state (UPDATE/DELETE only)
  "after": {                    # New row state (INSERT/UPDATE only)
    "id": 1,
    "name": "Alice",
    "email": "alice@example.com",
    "created_at": "2024-01-15 10:30:00"
  },
  "source": {                   # Source metadata
    "version": "0.1.0",
    "connector": "pgoutput-decoder",
    "name": "pgoutput-decoder",
    "ts_ms": 1705315800000,
    "snapshot": "false",
    "db": "mydb",
    "schema": "public",
    "table": "users",
    "lsn": 123456789
  },
  "ts_ms": 1705315800000,       # Timestamp in milliseconds
  "ts_us": 1705315800000000,    # Timestamp in microseconds (optional)
  "ts_ns": 1705315800000000000  # Timestamp in nanoseconds (optional)
}
```

### Operation Types

- **`"c"` (Create)**: INSERT operations - `after` contains new row, `before` is `None`
- **`"u"` (Update)**: UPDATE operations - `after` contains new values, `before` contains old values (requires `REPLICA IDENTITY FULL`)
- **`"d"` (Delete)**: DELETE operations - `before` contains deleted row, `after` is `None`

### Message Examples

**INSERT:**
```python
message.op == "c"
message.after == {"id": 1, "name": "Alice"}
message.before == None
```

**UPDATE:**
```python
message.op == "u"
message.after == {"id": 1, "name": "Alice Updated"}
message.before == {"id": 1, "name": "Alice"}
```

**DELETE:**
```python
message.op == "d"
message.before == {"id": 1, "name": "Alice"}
message.after == None
```

## Supported PostgreSQL Types

| PostgreSQL Type | Python Type |
|----------------|-------------|
| `bool` | `bool` |
| `int2`, `int4`, `int8` | `int` |
| `float4`, `float8` | `float` |
| `numeric`, `decimal` | `float` or `str` |
| `text`, `varchar`, `char` | `str` |
| `bytea` | `bytes` |
| `json`, `jsonb` | `dict` or `list` |
| `uuid` | `str` |
| `date`, `time`, `timestamp`, `timestamptz` | `str` (ISO 8601) |
| Arrays | `list` |
| Composite types | `dict` |

## Advanced Usage

### Manual LSN Acknowledgment

By default, LSNs are acknowledged automatically after each message is processed (`auto_acknowledge=True`). For more control over acknowledgment (e.g., batch processing, transactional guarantees), you can disable auto-acknowledgment:

```python
# Disable auto-acknowledgment for manual control
cdc_reader = pgoutput_decoder.LogicalReplicationReader(
    publication_name="test_pub",
    slot_name="test_slot",
    host="localhost",
    database="mydb",
    port=5432,
    user="postgres",
    password="password",
    auto_acknowledge=False,  # Manual LSN control
)

async for message in cdc_reader:
    try:
        # Process message...
        await process_message(message)
        
        # Manually acknowledge after successful processing
        await cdc_reader.acknowledge()
    except Exception as e:
        print(f"Failed to process message: {e}")
        # Don't acknowledge - will retry from this LSN on restart
        break
```

**When to use manual acknowledgment:**
- Batch processing: Acknowledge after processing N messages
- Transactional guarantees: Acknowledge only after committing to database
- Error handling: Skip acknowledgment on failure to replay messages
- Exactly-once processing: Coordinate acknowledgment with external systems

### Helper Functions

The library provides several helper functions for working with CDC messages:

#### `message_to_debezium_json(message, indent=2)`

Convert a message to JSON string in Debezium format. **This function is implemented in Rust for high performance.**

```python
from pgoutput_decoder import message_to_debezium_json

# Pretty-printed JSON with 2-space indentation (default)
json_str = message_to_debezium_json(message, indent=2)
print(json_str)

# Custom indentation (4 spaces)
json_str = message_to_debezium_json(message, indent=4)

# Compact JSON (no indentation)
json_str = message_to_debezium_json(message, indent=None)
```

#### `message_to_dict(message)`

Convert a message to a Python dictionary:

```python
from pgoutput_decoder import message_to_dict

msg_dict = message_to_dict(message)
# Returns: {"op": "c", "before": None, "after": {...}, "source": {...}, ...}
```

#### `format_operation(op)`

Convert operation codes to human-readable format:

```python
from pgoutput_decoder import format_operation

op_name = format_operation("c")  # Returns: "INSERT"
op_name = format_operation("u")  # Returns: "UPDATE"
op_name = format_operation("d")  # Returns: "DELETE"
```

#### `get_table_name(message)`

Extract fully-qualified table name from a message:

```python
from pgoutput_decoder import get_table_name

table = get_table_name(message)  # Returns: "public.customers"
```

### Filtering by Table

```python
async for message in cdc_reader:
    if message.source["table"] == "users":
        # Process only user table changes
        process_user_change(message)
```
```

### Error Handling

```python
try:
    async for message in cdc_reader:
        process_message(message)
except Exception as e:
    print(f"Replication error: {e}")
    await cdc_reader.stop()
```

### Manual Slot Management

The library requires you to manually create replication slots for safety. This prevents accidental slot creation that could lead to disk space issues if not properly monitored.

```python
# Create slot using psycopg2 or asyncpg before starting replication
import asyncpg

conn = await asyncpg.connect("postgresql://localhost/mydb")
await conn.execute(
    "SELECT pg_create_logical_replication_slot('my_slot', 'pgoutput')"
)
```

## Performance Considerations

- **Connection Pooling**: Each `LogicalReplicationReader` maintains a persistent connection
- **Backpressure**: The library uses buffered channels; slow consumers may experience latency
- **Type Conversion**: Complex types (arrays, JSON) have more overhead than primitives
- **Replica Identity**: Set `REPLICA IDENTITY FULL` to receive old values in UPDATE messages

## Architecture

```
┌─────────────────────────────────────────────┐
│           Python Application                │
│                                             │
│  async for message in cdc_reader:          │
│      process(message)                       │
└──────────────────┬──────────────────────────┘
                   │ Python asyncio
                   │
┌──────────────────▼──────────────────────────┐
│         PyO3 Bridge (Rust ↔ Python)        │
│                                             │
│  • pyo3-asyncio (event loop integration)   │
│  • Type conversion (Rust → Python)         │
└──────────────────┬──────────────────────────┘
                   │
┌──────────────────▼──────────────────────────┐
│      Rust Core (tokio-postgres)            │
│                                             │
│  • Replication connection                  │
│  • pgoutput binary decoder                 │
│  • Auto-reconnect with backoff             │
│  • Type conversion (PG → Rust)             │
└──────────────────┬──────────────────────────┘
                   │ PostgreSQL Protocol
                   │
┌──────────────────▼──────────────────────────┐
│          PostgreSQL Server                  │
│                                             │
│  • WAL stream via replication protocol     │
│  • pgoutput plugin                         │
└─────────────────────────────────────────────┘
```

## Development

### Prerequisites

- Rust 1.70+
- Python 3.9+
- PostgreSQL 12+ (with logical replication support)
- Docker (for running tests)

### Build from Source

```bash
# Clone repository
git clone https://github.com/yourusername/pgoutput-decoder
cd pgoutput-decoder

# Create virtual environment
uv venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install dependencies
uv pip install -e ".[dev]"

# Build Rust extension
maturin develop

# Run tests
pytest tests/
```

### Running Tests

Tests use testcontainers to spin up PostgreSQL instances:

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_replication.py -v

# Run with coverage
pytest tests/ --cov=pgoutput_decoder --cov-report=html
```

## Troubleshooting

### "replication slot does not exist"

Create the replication slot manually:

```sql
SELECT pg_create_logical_replication_slot('your_slot', 'pgoutput');
```

### "must be superuser or replication role"

Grant replication permission:

```sql
ALTER USER your_user WITH REPLICATION;
```

### Slot bloating disk space

Monitor and drop unused slots:

```sql
-- Check slot lag
SELECT slot_name, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn))
FROM pg_replication_slots;

-- Drop unused slot
SELECT pg_drop_replication_slot('unused_slot');
```

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Credits

Built with:
- [PyO3](https://github.com/PyO3/pyo3) - Rust ↔ Python bindings
- [tokio-postgres](https://github.com/sfackler/rust-postgres) - PostgreSQL client
- [maturin](https://github.com/PyO3/maturin) - Build tool for Rust Python extensions

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
