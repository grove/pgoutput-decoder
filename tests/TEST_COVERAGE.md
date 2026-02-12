# E-Commerce Schema Test Coverage

## Overview
Comprehensive end-to-end tests for the e-commerce schema using PostgreSQL 18.1 logical replication with the `pgoutput` plugin.

## Test Suite: `test_ecommerce_comprehensive.py`

### Tests Included (9 total - all passing ✅)

#### 1. **test_customer_crud_operations**
- **Coverage**: Basic CRUD operations on customers table
- **Operations tested**:
  - INSERT customer
  - UPDATE customer credit limit
  - Soft DELETE (UPDATE `_deleted` flag to TRUE)
- **Assertions**: Verifies all 3 operations captured with correct data

#### 2. **test_product_insert_and_update**
- **Coverage**: Product operations with decimal values
- **Operations tested**:
  - INSERT product with DECIMAL price
  - UPDATE product price
  - UPDATE product description
- **Assertions**: Verifies correct handling of DECIMAL(10,2) type

#### 3. **test_complete_order_workflow**
- **Coverage**: Multi-table related operations
- **Operations tested**:
  - INSERT customer
  - INSERT 2 products
  - INSERT order (with foreign key to customer)
  - INSERT 2 order lines (with foreign keys to order and products)
- **Assertions**: Verifies all 6 operations across 4 related tables

#### 4. **test_hard_delete_operations**
- **Coverage**: Hard DELETE (not soft delete)
- **Operations tested**:
  - INSERT customer
  - Hard DELETE customer (actual row removal)
- **Assertions**: Verifies DELETE message type and old column values

#### 5. **test_bulk_operations**
- **Coverage**: Bulk inserts
- **Operations tested**:
  - INSERT 5 customers in sequence
- **Assertions**: Verifies all 5 INSERT operations received with correct IDs

#### 6. **test_order_cancellation_cascade**
- **Coverage**: Cascading soft deletes across related tables
- **Operations tested**:
  - Setup: INSERT customer, product, order, order_line
  - Soft delete order (`_deleted` = TRUE)
  - Soft delete related order_line
- **Assertions**: Verifies 6 messages (4 inserts + 2 soft delete updates)

#### 7. **test_mixed_operations_single_transaction**
- **Coverage**: Multiple operations within a single transaction
- **Operations tested**:
  - BEGIN transaction
  - INSERT customer
  - INSERT product
  - UPDATE customer (in same transaction)
  - COMMIT transaction
- **Assertions**: Verifies correct sequencing across tables in one transaction

#### 8. **test_null_values_in_description**
- **Coverage**: NULL value handling
- **Operations tested**:
  - INSERT with NULL description
  - UPDATE to set description
  - UPDATE back to NULL
- **Assertions**: Verifies NULL values properly serialized

#### 9. **test_decimal_precision**
- **Coverage**: Decimal precision and range
- **Operations tested**:
  - INSERT products with various DECIMAL values:
    - 0.01 (minimum)
    - 99.99 (typical)
    - 1000.00 (whole number)
    - 12345.67 (large value)
- **Assertions**: Verifies precision maintained for all values

## Schema Coverage

### Tables Tested
- ✅ **customers** - Full CRUD + soft deletes
- ✅ **products** - INSERT, UPDATE, NULL values, DECIMAL handling
- ✅ **orders** - INSERT with foreign keys, soft deletes
- ✅ **order_lines** - INSERT with foreign keys, cascading soft deletes

### Data Types Tested
- ✅ **VARCHAR** - Primary keys and text fields
- ✅ **INTEGER** - credit_limit, quantity
- ✅ **DATE** - order_date
- ✅ **DECIMAL(10,2)** - price, unit_price (various precisions)
- ✅ **BOOLEAN** - _deleted flag
- ✅ **NULL** - Optional description field

### Operation Patterns Tested
- ✅ **INSERT** - Single and bulk
- ✅ **UPDATE** - Single column and multiple columns
- ✅ **DELETE** - Hard deletes (row removal)
- ✅ **Soft DELETE** - Boolean flag updates
- ✅ **Transactions** - Multi-operation transactions
- ✅ **Foreign Keys** - Related table operations
- ✅ **Cascading Changes** - Related record updates
- ✅ **NULL handling** - Setting and unsetting NULL values

## Test Infrastructure

### Setup
- **Container**: PostgreSQL 18.1-alpine via testcontainers
- **Configuration**: 
  - `wal_level=logical`
  - `max_replication_slots=10`
  - `max_wal_senders=10`
- **Replication**: 
  - Plugin: `pgoutput`
  - Slot: `ecommerce_slot`
  - Publication: `ecommerce_pub` (ALL TABLES)
- **Replica Identity**: FULL (for all tables)

### Test Pattern
Each test follows a consistent pattern:
1. Setup database schema (via fixture)
2. Perform SQL operations
3. Create LogicalReplicationReader
4. Collect messages with timeout
5. Assert expected message count and content
6. Clean up reader

## Results
**✅ All 9 tests passing**
- Execution time: ~15 seconds
- Full schema coverage
- All operation types tested
- All data types validated

## Usage
```bash
# Run all e-commerce tests
pytest tests/test_ecommerce_comprehensive.py -v

# Run specific test
pytest tests/test_ecommerce_comprehensive.py::test_complete_order_workflow -v

# Run with coverage
pytest tests/test_ecommerce_comprehensive.py --cov=pgoutput_decoder
```
