# pgoutput-decoder

[![PyPI](https://img.shields.io/pypi/v/pgoutput-decoder)](https://pypi.org/project/pgoutput-decoder/)
[![Python Versions](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/downloads/)
[![CI](https://github.com/yourusername/pgoutput-decoder/workflows/CI/badge.svg)](https://github.com/yourusername/pgoutput-decoder/actions)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Rust-powered PostgreSQL CDC (Change Data Capture) library with Debezium-compatible output for Python 3.12+**

Transform PostgreSQL changes into Debezium-format events with blazing-fast Rust performance and Python's async simplicity.

---

## 📋 Table of Contents

- [Features](#features)
- [Why pgoutput-decoder?](#why-pgoutput-decoder)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Use Cases](#use-cases)
- [PostgreSQL Setup](#postgresql-setup)
- [Message Format](#message-format)
- [Examples](#examples)
- [Advanced Usage](#advanced-usage)
- [Supported Types](#supported-postgresql-types)
- [Performance](#performance)
- [FAQ](#faq)
- [Testing](#testing)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [Development](#development)
- [Version Compatibility](#version-compatibility)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [License](#license)

## Features

### ⚡ Performance
- **Rust-Powered Core**: Critical path implemented in Rust using `tokio-postgres`
- **Zero-Copy Decoding**: Minimal allocations for high-throughput scenarios
- **Async/Await Native**: Built on `tokio` and `pyo3-asyncio` for true async Python integration

### 🔄 Compatibility

### 🔄 Compatibility
- **Debezium Format**: Drop-in compatible with Debezium CDC event format
- **pgoutput Plugin**: Uses PostgreSQL's native logical replication protocol
- **Python 3.12+**: Modern Python with full type hints

### 🛡️ Reliability
- **Auto-Reconnect**: Exponential backoff for connection failures
- **Manual LSN Control**: Optional manual acknowledgment for exactly-once processing
- **Type-Safe**: Comprehensive PostgreSQL type support with proper conversions

### 👨‍💻 Developer Experience
- **Simple API**: Pythonic async iteration over CDC events
- **Helper Functions**: Ready-to-use utilities for common tasks
- **Testcontainers**: Easy testing with ephemeral PostgreSQL instances
- **Comprehensive Examples**: Real-world usage patterns included

## Why pgoutput-decoder?

### What is CDC (Change Data Capture)?

CDC captures changes (inserts, updates, deletes) from your database and streams them as events. This enables:
- Real-time data synchronization
- Event-driven architectures
- Audit logging
- Cache invalidation
- Microservice data replication

### Comparison with Alternatives

| Feature | pgoutput-decoder | psycopg2 | py-postgresql | Pure Python |
|---------|-----------------|----------|---------------|-------------|
| **Performance** | 🟢 Native Rust | 🟡 C Extension | 🟡 C Extension | 🔴 Pure Python |
| **Async Support** | 🟢 Native async | 🔴 Sync only | 🟡 Limited | 🟢 asyncio |
| **Debezium Format** | 🟢 Built-in | 🔴 Manual | 🔴 Manual | 🔴 Manual |
| **Type Safety** | 🟢 Full | 🟡 Partial | 🟡 Partial | 🟡 Partial |
| **Auto-reconnect** | 🟢 Yes | 🔴 No | 🔴 No | 🔴 No |
| **Python 3.12+

| **Python 3.12+** | 🟢 Optimized | 🟡 Supported | 🟡 Supported | 🟡 Supported |

### When to Use pgoutput-decoder

✅ **Good fit when you need:**
- Real-time change streaming from PostgreSQL
- Debezium-compatible event format
- High-performance async Python CDC
- Simple, batteries-included solution
- Python 3.12+ modern features

❌ **Consider alternatives if:**
- You need Python < 3.12 support
- You're already using Debezium/Kafka Connect
- You only need occasional polling (triggers might be simpler)
- Your use case doesn't require sub-second latency

## Installation

### From PyPI (Recommended)

```bash
# Using uv (recommended)
uv pip install pgoutput-decoder

# Or using pip
pip install pgoutput-decoder
```

### From Source

Requires Rust 1.70+ and Python 3.12+:

```bash
git clone https://github.com/yourusername/pgoutput-decoder
cd pgoutput-decoder

# Using uv (recommended)
uv sync
uv run maturin develop

# Or using pip
pip install maturin
maturin develop
```

## Quick Start

### Prerequisites

Before running this example, ensure:
1. PostgreSQL 12+ with `wal_level = logical` (see [PostgreSQL Setup](#postgresql-setup))
2. A publication and replication slot created
3. User has `REPLICATION` privilege

### Basic Example

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
        # Access source metadata
        print(f"Table: {message.source['schema']}.{message.source['table']}")
        print(f"LSN: {message.source['lsn']}")
    
    # Stop when done
    await cdc_reader.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

### Expected Output

```python
# When you INSERT a row:
New row: {'id': 1, 'name': 'Alice', 'email': 'alice@example.com'}
Table: public.users
LSN: 0/1234ABC

# When you UPDATE a row:
Updated from {'id': 1, 'name': 'Alice'} to {'id': 1, 'name': 'Alice Smith'}
Table: public.users
LSN: 0/1234ABD

# When you DELETE a row:
Deleted row: {'id': 1, 'name': 'Alice Smith'}
Table: public.users
LSN: 0/1234ABE
```

### More Examples

- [Basic CDC Usage](examples/basic_cdc.py) - Simple monitoring with helper functions
- [Debezium Format Demo](example_debezium.py) - Working with Debezium-compatible messages
- [Manual Acknowledgment](example_debezium.py#L43) - Exactly-once processing patterns

## Use Cases

### 1. Real-Time Data Synchronization

Keep secondary databases, search indexes, or caches in sync:

```python
async for message in cdc_reader:
    if message.op == "c" or message.op == "u":
        # Update Elasticsearch index
        await es_client.index(
            index=message.source['table'],
            id=message.after['id'],
            document=message.after
        )
    elif message.op == "d":
        # Remove from index
        await es_client.delete(
            index=message.source['table'],
            id=message.before['id']
        )
```

### 2. Event-Driven Microservices

Publish database changes to message queues:

```python
from pgoutput_decoder import message_to_debezium_json

async for message in cdc_reader:
    # Publish to Kafka, RabbitMQ, etc.
    await kafka_producer.send(
        topic=f"db.{message.source['table']}",
        value=message_to_debezium_json(message)
    )
```

### 3. Audit Logging

Track all data changes with full history:

```python
async for message in cdc_reader:
    audit_entry = {
        "timestamp": message.ts_ms,
        "operation": message.op,
        "table": f"{message.source['schema']}.{message.source['table']}",
        "before": message.before,
        "after": message.after,
        "lsn": message.source['lsn']
    }
    await audit_log.write(audit_entry)
```

### 4. Cache Invalidation

Invalidate caches when data changes:

```python
async for message in cdc_reader:
    cache_key = f"{message.source['table']}:{message.after.get('id')}"
    await redis.delete(cache_key)
    logger.info(f"Invalidated cache: {cache_key}")
```

## PostgreSQL Setup

### Step-by-Step Configuration

#### 1. Enable Logical Replication

Edit `postgresql.conf` and restart PostgreSQL:

```conf
wal_level = logical
max_replication_slots = 10
max_wal_senders = 10
```

```bash
# On Linux
sudo systemctl restart postgresql

# On macOS (Homebrew)
brew services restart postgresql

# Verify settings
psql -c "SHOW wal_level;"  # Should output: logical
```

#### 2. Set Replica Identity (Critical!)

For UPDATE/DELETE operations to include old values:

```sql
-- For specific tables (recommended)

```sql
-- For specific tables (recommended)
ALTER TABLE users REPLICA IDENTITY FULL;
ALTER TABLE orders REPLICA IDENTITY FULL;

-- Or for all tables in schema (use cautiously)
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public'
    LOOP
        EXECUTE 'ALTER TABLE ' || quote_ident(r.tablename) || ' REPLICA IDENTITY FULL';
    END LOOP;
END$$;
```

> **⚠️ Warning**: `REPLICA IDENTITY FULL` increases WAL size. Only apply to tables where you need old values in UPDATE/DELETE events.

#### 3. Create Publication

```sql
-- Create a publication for specific tables
CREATE PUBLICATION my_pub FOR TABLE users, orders, products;

-- Or for all tables
CREATE PUBLICATION my_pub FOR ALL TABLES;

-- Verify
SELECT * FROM pg_publication;
```

#### 4. Create Replication Slot

```sql
-- Create a logical replication slot using pgoutput
SELECT pg_create_logical_replication_slot('my_slot', 'pgoutput');

-- Verify
SELECT * FROM pg_replication_slots;
```

#### 5. Grant Permissions

```sql
-- Grant replication permission to your user
ALTER USER myuser WITH REPLICATION;

-- Grant SELECT on published tables
GRANT SELECT ON ALL TABLES IN SCHEMA public TO myuser;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO myuser;
```

### Quick Start with Docker Compose

For local development and testing:

```yaml
# docker-compose.yml
version: '3.8'

services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: password
      POSTGRES_DB: testdb
    ports:
      - "5432:5432"
    command:
      - "postgres"
      - "-c"
      - "wal_level=logical"
      - "-c"
      - "max_replication_slots=10"
      - "-c"
      - "max_wal_senders=10"
    volumes:
      - ./examples/setup_postgres.sql:/docker-entrypoint-initdb.d/init.sql
```

```bash
# Start PostgreSQL
docker-compose up -d

# Run setup script
docker-compose exec postgres psql -U postgres -d testdb -f /docker-entrypoint-initdb.d/init.sql

# Test connection
python example_debezium.py
```

### Verify Configuration

```sql
-- Check WAL level
SHOW wal_level;  -- Must be 'logical'

-- Check replication slots
SELECT slot_name, slot_type, active FROM pg_replication_slots;

-- Check publications
SELECT pubname, puballtables FROM pg_publication;

-- Monitor replication lag
SELECT slot_name, 
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) as lag
FROM pg_replication_slots;
```

## Message Format

### What is Debezium?

[Debezium](https://debezium.io/) is a popular open-source CDC platform. This library produces events in Debezium's format, making it compatible with existing Debezium-based pipelines and tools.

### Message Structure

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

### Visual Operation Flow

```
DATABASE CHANGE          →    CDC EVENT           →    YOUR APPLICATION
─────────────────             ─────────────            ─────────────────
INSERT INTO users...     →    op: "c"             →    Create in cache
                              after: {new data}   →    Index in search
                              before: None             Send notification

UPDATE users SET...      →    op: "u"             →    Update cache
                              after: {new data}   →    Reindex search
                              before: {old data}       Audit the change

DELETE FROM users...     →    op: "d"             →    Remove from cache
                              after: None         →    Delete from search
                              before: {old data}       Log deletion
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

## Examples

All examples are in the [`examples/`](examples/) directory:

| Example | Description | Complexity |
|---------|-------------|------------|
| [setup_postgres.sql](examples/setup_postgres.sql) | PostgreSQL setup script with e-commerce schema | ⭐ |
| [basic_cdc.py](examples/basic_cdc.py) | Simple CDC monitoring with helper functions | ⭐⭐ |
| [example_debezium.py](example_debezium.py) | Debezium format demo with auto/manual acknowledgment | ⭐⭐ |

### Running Examples

```bash
# 1. Setup PostgreSQL (see PostgreSQL Setup section)

# 2. Run basic CDC example
python examples/basic_cdc.py

# 3. Try Debezium format demo
python example_debezium.py
```

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

## Performance

### Benchmarks

*(Benchmarks coming soon)*

### Performance Characteristics

- **Throughput**: Designed for high-volume streams (1000s of messages/sec)
- **Latency**: Sub-millisecond message processing overhead
- **Memory**: ~2-5 MB base overhead + message buffer
- **CPU**: Minimal Python GIL impact due to Rust core

### Optimization Tips

```python
# Batch acknowledgments for higher throughput
messages_batch = []
async for message in cdc_reader:
    messages_batch.append(message)
    
    if len(messages_batch) >= 100:
        await process_batch(messages_batch)
        await cdc_reader.acknowledge()  # Acknowledge batch
        messages_batch.clear()
```

## FAQ

### What is CDC and why do I need it?

**Change Data Capture (CDC)** is a design pattern that captures and streams database changes in real-time. Unlike polling, CDC:
- ✅ Has minimal database impact (uses WAL, not queries)
- ✅ Captures all changes in order
- ✅ Provides sub-second latency
- ✅ Doesn't miss changes between polls

### How is this different from database triggers?

| Feature | CDC (pgoutput-decoder) | Triggers |
|---------|----------------------|----------|
| **Performance** | No query overhead | Runs on every DML |
| **Decoupling** | External consumer | Tightly coupled |
| **Reliability** | Durable WAL | Transaction-dependent |
| **Replay** | Can replay from LSN | No replay capability |
| **Schema changes** | Handles gracefully | Requires trigger updates |

### Can I use this in production?

Yes, but consider:
- ✅ Monitor replication slots to prevent WAL bloat
- ✅ Set up alerting for replication lag
- ✅ Test failover/recovery scenarios
- ✅ Use manual acknowledgment for critical workloads
- ⚠️ This library is in active development (v0.1.x)

### How do I handle schema changes?

Schema changes are captured in the WAL but may require application updates:

```python
async for message in cdc_reader:
    try:
        # Your processing logic
        process_message(message)
    except KeyError as e:
        # Handle missing columns in old messages
        logger.warning(f"Schema mismatch: {e}")
    except Exception as e:
        # Handle unexpected data types
        logger.error(f"Processing error: {e}")
```

### What happens if my consumer crashes?

The replication slot preserves your position (LSN):
- ✅ WAL data is retained from your last acknowledged LSN
- ✅ On restart, you resume from where you left off
- ⚠️ Un-acknowledged messages will be replayed
- ⚠️ Monitor slot lag to prevent WAL disk space issues

### How do I monitor replication lag?

```sql
-- Check replication lag
SELECT 
    slot_name,
    active,
    pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) as lag_size,
    pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn) as lag_bytes
FROM pg_replication_slots
WHERE slot_name = 'your_slot';
```

Set up monitoring alerts when `lag_size` exceeds acceptable thresholds (e.g., >1GB).

## Testing

### Running Tests Locally

Tests use [Testcontainers](https://testcontainers-python.readthedocs.io/) to spin up ephemeral PostgreSQL instances:

```bash
# Ensure Docker is running
docker ps

# Run all tests
uv run pytest tests/ -v

# Run specific test file
uv run pytest tests/test_ecommerce_comprehensive.py -v

# Run with coverage
uv run pytest tests/ --cov=pgoutput_decoder --cov-report=html
```

### Test Structure

```
tests/
├── test_ecommerce_comprehensive.py  # E2E tests with realistic schema
├── test_acknowledgement.py          # LSN acknowledgment tests
├── test_json_serialization.py       # Debezium format validation
└── test_types.py                    # PostgreSQL type conversion
```

All tests use PostgreSQL 18.1 via Testcontainers and follow the patterns in [AGENTS.md](AGENTS.md).

## Security

### Principle of Least Privilege

Grant only necessary permissions:

```sql
-- Create dedicated replication user
CREATE USER cdc_user WITH REPLICATION PASSWORD 'secure_password';

-- Grant only SELECT on published tables
GRANT SELECT ON TABLE users, orders, products TO cdc_user;

-- Do NOT grant: INSERT, UPDATE, DELETE, or superuser
```

### Connection Security

```python
# Use environment variables, never hardcode credentials
import os

cdc_reader = pgoutput_decoder.LogicalReplicationReader(
    publication_name="my_pub",
    slot_name="my_slot",
    host=os.getenv("PG_HOST", "localhost"),
    database=os.getenv("PG_DATABASE"),
    port=int(os.getenv("PG_PORT", "5432")),
    user=os.getenv("PG_USER"),
    password=os.getenv("PG_PASSWORD"),
)
```

### SSL/TLS

```python
# Enable SSL (implementation depends on tokio-postgres configuration)
# Currently supported via connection parameters
# See: https://www.postgresql.org/docs/current/libpq-ssl.html
```

### Audit Logging

Monitor replication activity:

```sql
-- Enable connection logging in postgresql.conf
log_connections = on
log_disconnections = on

-- Check active replication connections
SELECT * FROM pg_stat_replication;
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
SELECT slot_name, pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)) as lag
FROM pg_replication_slots;

-- Drop unused slot
SELECT pg_drop_replication_slot('unused_slot');
```

### "permission denied for table"

Grant SELECT permission:

```sql
GRANT SELECT ON ALL TABLES IN SCHEMA public TO your_user;
```

### Connection keeps dropping

Check your firewall/network settings and enable auto-reconnect (enabled by default).

### Missing "before" values in UPDATE/DELETE

Set `REPLICA IDENTITY FULL`:

```sql
ALTER TABLE your_table REPLICA IDENTITY FULL;
```

### Debugging Tips

```python
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

# Check PostgreSQL logs
# tail -f /var/log/postgresql/postgresql-16-main.log
```

## Development

### Prerequisites

- **Rust**: 1.70+ (from [Cargo.toml](Cargo.toml))
- **Python**: 3.12+ only
- **PostgreSQL**: 12+ (with logical replication support)
- **Docker**: For running tests
- **uv**: Python package manager (recommended)

### Setup Development Environment

```bash
# Clone repository
git clone https://github.com/yourusername/pgoutput-decoder
cd pgoutput-decoder

# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync dependencies
uv sync

# Build Rust extension in development mode
uv run maturin develop

# Run tests
uv run pytest tests/ -v
```

### Development Workflow

Per [AGENTS.md](AGENTS.md):

```bash
# Lint Python code
uv run ruff check .
uv run ruff format .

# Lint Rust code
cargo fmt --all -- --check
cargo clippy --all-targets --all-features

# Run tests
uv run pytest tests/ -v

# Build release
uv run maturin build --release
```

#### Code Coverage

The project supports both Python and Rust code coverage:

```bash
# Python coverage only (skips Docker tests)
just coverage

# Rust coverage only (skips Docker tests, requires cargo-llvm-cov)
just install-llvm-cov  # One-time installation
just coverage-rust

# Combined Python + Rust coverage (skips Docker tests)
just coverage-all

# Include Docker tests (requires Docker running)
just coverage-docker              # Python only with Docker
just coverage-rust-docker         # Rust with Docker
just coverage-all-docker          # Both with Docker
```

**Local Development**: By default, coverage commands skip Docker-dependent tests for faster iteration. Use the `-docker` variants when you need complete coverage including integration tests.

**GitHub Actions**: CI automatically generates and uploads both Python and Rust coverage to Codecov:
- **Python coverage**: Measures `python/pgoutput_decoder/` code
- **Rust coverage**: Measures `src/` code exercised by Python tests
- **Flags**: Separate `python` and `rust` flags for tracking

View coverage reports at: `https://codecov.io/gh/yourusername/pgoutput-decoder`

### Project Structure

```
pgoutput-decoder/
├── src/                  # Rust source code
│   ├── lib.rs           # PyO3 module definitions
│   ├── pgoutput/        # pgoutput decoder implementation
│   └── replication.rs   # Replication connection logic
├── python/              # Python source code
│   └── pgoutput_decoder/
│       ├── __init__.py  # Python API
│       └── core.py      # Helper functions
├── tests/               # Test suite (uses testcontainers)
├── examples/            # Example scripts
├── Cargo.toml           # Rust dependencies
├── pyproject.toml       # Python metadata & build config
└── README.md            # This file
```

### Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure `cargo fmt`, `cargo clippy`, and `ruff` pass
5. Submit a pull request

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines (if available).

## Version Compatibility

### Supported Versions

| Component | Version | Status |
|-----------|---------|--------|
| **Python** | 3.12+ | ✅ Required |
| **PostgreSQL** | 12+ | ✅ Tested |
| **PostgreSQL** | 13-16 | ✅ Tested |
| **Rust** | 1.70+ | ✅ Required |
| **PyO3** | 0.20 | ✅ Current |

### Python Version Support

This library **requires Python 3.12 or later** and uses:
- Modern type hints
- `async`/`await` patterns
- PyO3 0.20 with `abi3-py312`

**Why Python 3.12+?**
- Better performance
- Improved async capabilities
- Modern standard library features
- Rust binding compatibility

### PostgreSQL Version Testing

Tested with:
- PostgreSQL 12 (minimum)
- PostgreSQL 13, 14, 15, 16 (CI tested)
- PostgreSQL 18.1-alpine (testcontainer default)

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

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Credits

Built with:
- [PyO3](https://github.com/PyO3/pyo3) - Rust ↔ Python bindings
- [tokio-postgres](https://github.com/sfackler/rust-postgres) - PostgreSQL async client
- [maturin](https://github.com/PyO3/maturin) - Build tool for Rust Python extensions
- [Debezium](https://debezium.io/) - Inspiration for message format

Inspired by and compatible with the [Debezium](https://debezium.io/) CDC ecosystem.

---

### 📚 Resources

- **Documentation**: [Full API Docs](#) *(coming soon)*
- **Examples**: [examples/](examples/)
- **Issues**: [GitHub Issues](https://github.com/yourusername/pgoutput-decoder/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/pgoutput-decoder/discussions)

### 💝 Support

If you find this project useful, please⭐ star the repository on GitHub!

---

*Built with ❤️ using Rust and Python*
