# Test Suite Documentation

## Overview

The test suite contains comprehensive end-to-end tests using **PostgreSQL 18.1** via testcontainers. Tests cover real-world e-commerce schema with foreign key relationships, various data types, and CDC operations.

## Test Structure

### Test Files

1. **`test_replication.py`** (7 tests)
   - Basic INSERT/UPDATE/DELETE operations
   - Soft deletes using `_deleted` flag
   - Product price updates with DECIMAL type
   - Multi-table order workflows
   - API specification compliance

2. **`test_ecommerce_workflow.py`** (5 tests)
   - Complete e-commerce workflow simulation
   - Concurrent operations across tables
   - Foreign key relationship handling
   - NULL value handling
   - Large DECIMAL values

3. **`test_types.py`** (6 tests)
   - Type conversion verification
   - DECIMAL, INTEGER, VARCHAR, BOOLEAN handling
   - Module import tests

**Total: 18 tests**

## Database Schema

The tests use a realistic e-commerce schema:

```sql
-- Customers
CREATE TABLE customers (
    _id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    credit_limit INTEGER NOT NULL,
    _deleted BOOLEAN DEFAULT FALSE
);

-- Products
CREATE TABLE products (
    _id VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    description VARCHAR,
    price DECIMAL(10,2) NOT NULL,
    _deleted BOOLEAN DEFAULT FALSE
);

-- Orders
CREATE TABLE orders (
    _id VARCHAR PRIMARY KEY,
    cust_id VARCHAR NOT NULL,
    order_date DATE NOT NULL,
    _deleted BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (cust_id) REFERENCES customers(_id)
);

-- Order Lines
CREATE TABLE order_lines (
    _id VARCHAR PRIMARY KEY,
    order_id VARCHAR NOT NULL,
    product_id VARCHAR NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    _deleted BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (order_id) REFERENCES orders(_id),
    FOREIGN KEY (product_id) REFERENCES products(_id)
);
```

## Running Tests

### Prerequisites

```bash
# Install dependencies
uv pip install -e ".[dev]"

# Build Rust extension
maturin develop

# Docker must be running for testcontainers
docker ps
```

### Run All Tests

```bash
pytest tests/ -v
```

### Run Specific Test Module

```bash
# E-commerce workflow tests
pytest tests/test_ecommerce_workflow.py -v

# Basic replication tests
pytest tests/test_replication.py -v

# Type conversion tests
pytest tests/test_types.py -v
```

### Run Single Test

```bash
pytest tests/test_ecommerce_workflow.py::test_complete_ecommerce_workflow -v
```

### Run with Coverage

```bash
pytest tests/ --cov=pgoutput_decoder --cov-report=html
open htmlcov/index.html
```

## Test Scenarios

### 1. Customer Insert
Tests basic INSERT operation capture for customers table.

### 2. Complete Order Workflow
Simulates a full order:
- Create customer
- Add products to catalog
- Create order
- Add order lines (multiple items)

**Expected CDC Events:** 6 INSERTs (1 customer + 2 products + 1 order + 2 order_lines)

### 3. Soft Delete
Tests UPDATE operation where `_deleted` flag is set to `TRUE`.

**Expected CDC Events:** INSERT + UPDATE

### 4. Product Price Update
Tests UPDATE operation with DECIMAL type precision.

**Expected CDC Events:** INSERT + UPDATE

### 5. Order Deletion
Tests hard DELETE operation.

**Expected CDC Events:** 2 INSERTs + 1 DELETE

### 6. Multiple Type Handling
Tests VARCHAR, INTEGER, DECIMAL, BOOLEAN, and DATE types in a single workflow.

**Expected CDC Events:** 4 INSERTs (customer + product + order + order_line)

### 7. Complete Workflow
Complex scenario with 12 operations:
- 1 customer INSERT
- 3 product INSERTs
- 1 order INSERT
- 3 order_line INSERTs
- 1 product UPDATE (price change)
- 1 order_line UPDATE (soft delete)
- 1 customer UPDATE (credit limit)
- 1 order_line DELETE (hard delete)

### 8. Concurrent Operations
Tests parallel INSERTs across multiple customers.

### 9. Foreign Key Cascade
Verifies CDC capture with FK relationships.

### 10. NULL Values
Tests handling of NULL in optional columns (product description).

### 11. Large Decimals
Tests DECIMAL(10,2) with large values (99999.99).

## Fixtures

### `postgres_container`
- **Scope:** module
- **Image:** postgres:18.1-alpine
- **Config:** wal_level=logical, max_replication_slots=4

### `postgres_with_ecommerce_schema`
- **Scope:** function (fresh DB per test)
- **Setup:**
  - Creates all 4 tables
  - Sets REPLICA IDENTITY FULL on all tables
  - Creates publication `ecommerce_pub`
  - Creates replication slot `ecommerce_slot`
- **Yields:** Connection config dict

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:18.1-alpine
        env:
          POSTGRES_PASSWORD: test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    
    steps:
      - uses: actions/checkout@v3
      
      - uses: actions/setup-python@v4
        with:
          python-version: '3.9'
      
      - name: Install Rust
        uses: actions-rs/toolchain@v1
        with:
          toolchain: stable
      
      - name: Build and Test
        run: |
          pip install maturin uv
          maturin develop
          uv pip install -e ".[dev]"
          pytest tests/ -v
```

## Troubleshooting

### Docker Not Running
```
Error: Cannot connect to the Docker daemon
```
**Solution:** Start Docker Desktop or Docker daemon

### Port Conflicts
```
Error: Port 5432 already in use
```
**Solution:** Testcontainers automatically assigns random ports

### Slot Already Exists
```
Error: replication slot "ecommerce_slot" already exists
```
**Solution:** Tests automatically clean up slots. If persisting, manually drop:
```sql
SELECT pg_drop_replication_slot('ecommerce_slot');
```

### Connection Timeout
```
Error: asyncio timeout waiting for connection
```
**Solution:** Increase timeout or check container health:
```bash
docker ps
docker logs <container_id>
```

## Performance

- **Average test duration:** ~2-5 seconds per test
- **Container startup:** ~3-4 seconds
- **Schema setup:** ~500ms
- **Full suite:** ~30-60 seconds

## Future Enhancements

- [ ] Benchmark tests for high-volume CDC
- [ ] Schema migration tests
- [ ] Network failure recovery tests
- [ ] Snapshot tests with pre-populated data
- [ ] Performance regression tests
- [ ] Multi-publication tests
