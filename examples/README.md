# pgoutput-decoder Examples

This directory contains example code showing how to use `pgoutput-decoder` in different scenarios.

## Quick Start

All examples assume you have:
1. PostgreSQL 12+ with `wal_level=logical`
2. A database with some tables
3. A publication created: `CREATE PUBLICATION my_pub FOR ALL TABLES;`

## Example Files

### Async Examples (Recommended)

#### [basic_cdc.py](basic_cdc.py) 
**Start here!** Simple async CDC consumer using `async for`.

```bash
python examples/basic_cdc.py
```

**Best for:** Learning the basics, async applications, modern Python code

---

### Synchronous Examples

If you have an existing synchronous application and can't easily convert to async:

#### [sync_wrapper.py](sync_wrapper.py) ⭐
Simple wrapper using `asyncio.run()` for synchronous scripts.

```bash
python examples/sync_wrapper.py
```

**Best for:**
- Simple scripts and CLI tools
- Batch processing jobs  
- Applications that can block on CDC messages
- Learning how to integrate CDC into sync code

**Pros:** Dead simple, just wrap in a function
**Cons:** Blocks the entire process

---

#### [background_thread.py](background_thread.py) ⭐⭐⭐
Background thread pattern for long-running sync applications.

```bash
python examples/background_thread.py
```

**Best for:**
- Flask, Django, or other web frameworks
- Long-running services with existing sync code
- Applications that need to do other work while monitoring CDC
- Microservices needing CDC as a side-channel

**Pros:** 
- Integrates cleanly with sync code
- Thread-safe message queue
- Natural backpressure handling
- Non-blocking message retrieval

**Cons:** 
- Threading overhead
- Need careful error handling

**This is the recommended pattern for most sync applications.**

---

#### [celery_integration.py](celery_integration.py)
Dispatch CDC messages to Celery tasks for distributed processing.

```bash
# Terminal 1: Start Celery worker
celery -A examples.celery_integration worker --loglevel=info

# Terminal 2: Run CDC consumer
python examples/celery_integration.py
```

**Best for:**
- Distributed systems
- Horizontal scaling
- Long-running message processing
- Fault-tolerant workflows

**Prerequisites:** Redis or RabbitMQ

---

#### [django_command.py](django_command.py)
Django management command for CDC processing.

```bash
python manage.py consume_cdc --max-messages=10
```

**Best for:**
- Django projects
- Running as a separate process/container
- Integration with Django ORM

**Usage:** Copy to `your_app/management/commands/consume_cdc.py`

---

## Which Example Should I Use?

```
┌─────────────────────────────────────────────────────────────┐
│ Starting a NEW project?                                     │
│ └─> Use basic_cdc.py (async)                               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Have EXISTING sync code (Flask, Django, legacy)?           │
│ └─> Use background_thread.py                               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Need DISTRIBUTED processing (multiple workers)?            │
│ └─> Use celery_integration.py                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Simple SCRIPT that processes N messages then exits?        │
│ └─> Use sync_wrapper.py                                    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Django project?                                             │
│ └─> Use django_command.py                                  │
└─────────────────────────────────────────────────────────────┘
```

## Common Patterns

### Pattern 1: Process N Messages Then Exit
```python
# See sync_wrapper.py, example_simple()
consume_cdc_messages(
    ...,
    callback=my_handler,
    max_messages=100  # Stop after 100 messages
)
```

### Pattern 2: Continuously Monitor (Ctrl+C to stop)
```python
# See basic_cdc.py or sync_wrapper.py, example_continuous()
try:
    async for message in reader:  # or consume_cdc_messages(..., max_messages=None)
        process(message)
except KeyboardInterrupt:
    print("Stopping...")
```

### Pattern 3: Table-Specific Logic
```python
def handle_message(message):
    table = get_table_name(message)
    
    if table == "public.orders":
        handle_order_change(message)
    elif table == "public.customers":
        handle_customer_change(message)
```

### Pattern 4: Operation-Specific Logic
```python
def handle_message(message):
    if message.op == "c":  # INSERT
        handle_create(message.after)
    elif message.op == "u":  # UPDATE
        handle_update(message.before, message.after)
    elif message.op == "d":  # DELETE
        handle_delete(message.before)
```

## Testing Examples Locally

### 1. Start PostgreSQL with Logical Replication
```bash
# docker-compose.yml
version: '3.8'
services:
  postgres:
    image: postgres:18.1-alpine
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
      POSTGRES_DB: ecommerce_db
    ports:
      - "5432:5432"
    command:
      - postgres
      - -c
      - wal_level=logical
      - -c
      - max_replication_slots=4
      - -c
      - max_wal_senders=4

# Start it
docker-compose up -d
```

### 2. Create Test Schema
```sql
-- Connect to the database
psql -h localhost -U postgres -d ecommerce_db

-- Create tables
CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id),
    total DECIMAL(10,2),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Create publication
CREATE PUBLICATION ecommerce_pub FOR ALL TABLES;

-- Verify
SELECT * FROM pg_publication;
```

### 3. Run Examples
```bash
# In one terminal, run an example
python examples/basic_cdc.py

# In another terminal, make some changes
psql -h localhost -U postgres -d ecommerce_db

INSERT INTO customers (name, email) VALUES ('Alice', 'alice@example.com');
INSERT INTO orders (customer_id, total) VALUES (1, 99.99);
UPDATE customers SET name = 'Alice Smith' WHERE id = 1;
DELETE FROM orders WHERE id = 1;
```

You should see CDC messages appear in the first terminal!

## Troubleshooting

### "No module named 'pgoutput_decoder'"
```bash
# Install in development mode
uv sync
uv run maturin develop

# Or install from PyPI
pip install pgoutput-decoder
```

### "Connection refused" or "Permission denied"
```bash
# Check PostgreSQL is running
docker ps

# Check connection settings
psql -h localhost -U postgres -d ecommerce_db

# Verify wal_level
psql -c "SHOW wal_level;"  # Should be 'logical'
```

### "Publication does not exist"
```sql
-- Create it
CREATE PUBLICATION my_pub FOR ALL TABLES;

-- Or for specific tables
CREATE PUBLICATION my_pub FOR TABLE customers, orders;
```

### "Replication slot already exists"
```python
# Use a unique slot name per consumer
LogicalReplicationReader(
    slot_name="unique_slot_name_123",  # Make this unique
    ...
)
```

```sql
-- Or drop existing slot
SELECT pg_drop_replication_slot('slot_name');
```

## Next Steps

- Read the [main README](../README.md) for more details
- Check out the [API documentation](../README.md#api-reference)
- See [test files](../tests/) for more usage examples
- Join discussions on GitHub for help

## Contributing

Found a bug or want to add an example? PRs welcome!

1. Fork the repo
2. Create a feature branch
3. Add your example with clear documentation
4. Submit a PR

Please ensure examples:
- Have clear docstrings
- Include inline comments for beginners
- Show error handling
- Demonstrate best practices
