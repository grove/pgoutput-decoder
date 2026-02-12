"""Comprehensive end-to-end tests for e-commerce schema with logical replication."""

import asyncio
from datetime import date
from decimal import Decimal

import asyncpg
import pytest
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.docker


@pytest.fixture(scope="function")
async def ecommerce_db():
    """Set up PostgreSQL with e-commerce schema and logical replication."""
    postgres = PostgresContainer(
        image="postgres:18.1-alpine",
        username="test",
        password="test",
        dbname="ecommerce",
    )
    postgres.with_command(
        "postgres -c wal_level=logical -c max_replication_slots=10 -c max_wal_senders=10"
    )

    with postgres:
        conn = await asyncpg.connect(
            host=postgres.get_container_host_ip(),
            port=postgres.get_exposed_port(5432),
            user="test",
            password="test",
            database="ecommerce",
        )

        # Create schema
        await conn.execute("""
            CREATE TABLE customers (
                _id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                credit_limit INTEGER NOT NULL,
                _deleted BOOLEAN DEFAULT FALSE
            )
        """)

        await conn.execute("""
            CREATE TABLE orders (
                _id VARCHAR PRIMARY KEY,
                cust_id VARCHAR NOT NULL,
                order_date DATE NOT NULL,
                _deleted BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (cust_id) REFERENCES customers(_id)
            )
        """)

        await conn.execute("""
            CREATE TABLE products (
                _id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                description VARCHAR,
                price DECIMAL(10,2) NOT NULL,
                _deleted BOOLEAN DEFAULT FALSE
            )
        """)

        await conn.execute("""
            CREATE TABLE order_lines (
                _id VARCHAR PRIMARY KEY,
                order_id VARCHAR NOT NULL,
                product_id VARCHAR NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price DECIMAL(10,2) NOT NULL,
                _deleted BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (order_id) REFERENCES orders(_id),
                FOREIGN KEY (product_id) REFERENCES products(_id)
            )
        """)

        # Set replica identity FULL for all tables
        for table in ["customers", "orders", "products", "order_lines"]:
            await conn.execute(f"ALTER TABLE {table} REPLICA IDENTITY FULL")

        # Create publication
        await conn.execute("CREATE PUBLICATION ecommerce_pub FOR ALL TABLES")

        # Create replication slot
        await conn.execute(
            "SELECT pg_create_logical_replication_slot('ecommerce_slot', 'pgoutput')"
        )

        yield {
            "connection": conn,
            "host": postgres.get_container_host_ip(),
            "port": postgres.get_exposed_port(5432),
            "database": "ecommerce",
            "user": "test",
            "password": "test",
        }

        await conn.close()


@pytest.mark.asyncio
async def test_customer_crud_operations(ecommerce_db):
    """Test INSERT, UPDATE, and soft DELETE on customers table."""
    import pgoutput_decoder

    conn = ecommerce_db["connection"]

    # Insert customer
    await conn.execute(
        """INSERT INTO customers (_id, name, credit_limit, _deleted)
           VALUES ($1, $2, $3, $4)""",
        "CUST001",
        "Alice Johnson",
        5000,
        False,
    )

    # Update customer credit limit
    await conn.execute("UPDATE customers SET credit_limit = $1 WHERE _id = $2", 7500, "CUST001")

    # Soft delete customer
    await conn.execute("UPDATE customers SET _deleted = TRUE WHERE _id = $1", "CUST001")

    # Create reader
    reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="ecommerce_pub",
        slot_name="ecommerce_slot",
        host=ecommerce_db["host"],
        database=ecommerce_db["database"],
        port=ecommerce_db["port"],
        user=ecommerce_db["user"],
        password=ecommerce_db["password"],
    )

    # Collect messages
    messages = []

    async def collect_messages():
        count = 0
        async for message in reader:
            if message is not None:
                messages.append(message)
                count += 1
                if count >= 3:  # INSERT, UPDATE, UPDATE (soft delete)
                    break

    try:
        await asyncio.wait_for(collect_messages(), timeout=10.0)
    except asyncio.TimeoutError:
        pass

    await reader.stop()

    # Verify we got all operations
    assert len(messages) == 3, f"Expected 3 messages, got {len(messages)}"

    # Verify INSERT
    assert messages[0].op == "c"
    assert messages[0].source["table"] == "customers"
    assert messages[0].after["_id"] == "CUST001"
    assert messages[0].after["name"] == "Alice Johnson"
    assert messages[0].after["credit_limit"] == 5000
    assert messages[0].after["_deleted"] is False

    # Verify UPDATE (credit limit change)
    assert messages[1].op == "u"
    assert messages[1].source["table"] == "customers"
    assert messages[1].after["credit_limit"] == 7500

    # Verify UPDATE (soft delete)
    assert messages[2].op == "u"
    assert messages[2].source["table"] == "customers"
    assert messages[2].after["_deleted"] is True


@pytest.mark.asyncio
async def test_product_insert_and_update(ecommerce_db):
    """Test product operations with decimal prices."""
    import pgoutput_decoder

    conn = ecommerce_db["connection"]

    # Insert product
    await conn.execute(
        """INSERT INTO products (_id, name, description, price, _deleted)
           VALUES ($1, $2, $3, $4, $5)""",
        "PROD001",
        "Laptop",
        "High-performance laptop",
        Decimal("999.99"),
        False,
    )

    # Update product price
    await conn.execute(
        "UPDATE products SET price = $1 WHERE _id = $2", Decimal("1099.99"), "PROD001"
    )

    # Update description
    await conn.execute(
        "UPDATE products SET description = $1 WHERE _id = $2",
        "Premium high-performance laptop",
        "PROD001",
    )

    reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="ecommerce_pub",
        slot_name="ecommerce_slot",
        host=ecommerce_db["host"],
        database=ecommerce_db["database"],
        port=ecommerce_db["port"],
        user=ecommerce_db["user"],
        password=ecommerce_db["password"],
    )

    messages = []

    async def collect_messages():
        count = 0
        async for message in reader:
            if message is not None:
                messages.append(message)
                count += 1
                if count >= 3:
                    break

    try:
        await asyncio.wait_for(collect_messages(), timeout=10.0)
    except asyncio.TimeoutError:
        pass

    await reader.stop()

    assert len(messages) == 3

    # Verify INSERT
    assert messages[0].op == "c"
    assert messages[0].source["table"] == "products"
    assert messages[0].after["_id"] == "PROD001"
    assert messages[0].after["name"] == "Laptop"
    assert float(messages[0].after["price"]) == 999.99

    # Verify price UPDATE
    assert messages[1].op == "u"
    assert float(messages[1].after["price"]) == 1099.99

    # Verify description UPDATE
    assert messages[2].op == "u"
    assert messages[2].after["description"] == "Premium high-performance laptop"


@pytest.mark.asyncio
async def test_complete_order_workflow(ecommerce_db):
    """Test complete order creation with customer, products, and order lines."""
    import pgoutput_decoder

    conn = ecommerce_db["connection"]

    # Insert customer
    await conn.execute(
        """INSERT INTO customers (_id, name, credit_limit, _deleted)
           VALUES ($1, $2, $3, $4)""",
        "CUST002",
        "Bob Smith",
        10000,
        False,
    )

    # Insert products
    await conn.execute(
        """INSERT INTO products (_id, name, description, price, _deleted)
           VALUES ($1, $2, $3, $4, $5)""",
        "PROD002",
        "Mouse",
        "Wireless mouse",
        Decimal("29.99"),
        False,
    )
    await conn.execute(
        """INSERT INTO products (_id, name, description, price, _deleted)
           VALUES ($1, $2, $3, $4, $5)""",
        "PROD003",
        "Keyboard",
        "Mechanical keyboard",
        Decimal("89.99"),
        False,
    )

    # Insert order
    await conn.execute(
        """INSERT INTO orders (_id, cust_id, order_date, _deleted)
           VALUES ($1, $2, $3, $4)""",
        "ORD001",
        "CUST002",
        date(2026, 2, 12),
        False,
    )

    # Insert order lines
    await conn.execute(
        """INSERT INTO order_lines (_id, order_id, product_id, quantity, unit_price, _deleted)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        "LINE001",
        "ORD001",
        "PROD002",
        2,
        Decimal("29.99"),
        False,
    )
    await conn.execute(
        """INSERT INTO order_lines (_id, order_id, product_id, quantity, unit_price, _deleted)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        "LINE002",
        "ORD001",
        "PROD003",
        1,
        Decimal("89.99"),
        False,
    )

    reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="ecommerce_pub",
        slot_name="ecommerce_slot",
        host=ecommerce_db["host"],
        database=ecommerce_db["database"],
        port=ecommerce_db["port"],
        user=ecommerce_db["user"],
        password=ecommerce_db["password"],
    )

    messages = []

    async def collect_messages():
        count = 0
        async for message in reader:
            if message is not None:
                messages.append(message)
                count += 1
                if count >= 6:  # 1 customer + 2 products + 1 order + 2 order lines
                    break

    try:
        await asyncio.wait_for(collect_messages(), timeout=10.0)
    except asyncio.TimeoutError:
        pass

    await reader.stop()

    assert len(messages) == 6, f"Expected 6 messages, got {len(messages)}"

    # Group messages by table
    by_table = {}
    for msg in messages:
        table = msg.source["table"]
        if table not in by_table:
            by_table[table] = []
        by_table[table].append(msg)

    # Verify we have messages from all tables
    assert "customers" in by_table
    assert "products" in by_table
    assert "orders" in by_table
    assert "order_lines" in by_table

    # Verify customer
    assert len(by_table["customers"]) == 1
    assert by_table["customers"][0].after["_id"] == "CUST002"

    # Verify products
    assert len(by_table["products"]) == 2
    product_ids = {msg.after["_id"] for msg in by_table["products"]}
    assert product_ids == {"PROD002", "PROD003"}

    # Verify order
    assert len(by_table["orders"]) == 1
    order_msg = by_table["orders"][0]
    assert order_msg.after["_id"] == "ORD001"
    assert order_msg.after["cust_id"] == "CUST002"

    # Verify order lines
    assert len(by_table["order_lines"]) == 2
    for line_msg in by_table["order_lines"]:
        assert line_msg.after["order_id"] == "ORD001"


@pytest.mark.asyncio
async def test_hard_delete_operations(ecommerce_db):
    """Test hard DELETE operations (not soft deletes)."""
    import pgoutput_decoder

    conn = ecommerce_db["connection"]

    # Insert and then hard delete a customer
    await conn.execute(
        """INSERT INTO customers (_id, name, credit_limit, _deleted)
           VALUES ($1, $2, $3, $4)""",
        "CUST003",
        "Charlie Brown",
        3000,
        False,
    )

    await conn.execute("DELETE FROM customers WHERE _id = $1", "CUST003")

    reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="ecommerce_pub",
        slot_name="ecommerce_slot",
        host=ecommerce_db["host"],
        database=ecommerce_db["database"],
        port=ecommerce_db["port"],
        user=ecommerce_db["user"],
        password=ecommerce_db["password"],
    )

    messages = []

    async def collect_messages():
        count = 0
        async for message in reader:
            if message is not None:
                messages.append(message)
                count += 1
                if count >= 2:  # INSERT + DELETE
                    break

    try:
        await asyncio.wait_for(collect_messages(), timeout=10.0)
    except asyncio.TimeoutError:
        pass

    await reader.stop()

    assert len(messages) == 2

    # Verify INSERT
    assert messages[0].op == "c"
    assert messages[0].after["_id"] == "CUST003"

    # Verify DELETE
    assert messages[1].op == "d"
    assert messages[1].source["table"] == "customers"
    assert messages[1].before["_id"] == "CUST003"
    assert messages[1].after is None


@pytest.mark.asyncio
async def test_bulk_operations(ecommerce_db):
    """Test bulk insert operations."""
    import pgoutput_decoder

    conn = ecommerce_db["connection"]

    # Bulk insert customers
    customer_data = [
        ("CUST010", "Customer 10", 1000),
        ("CUST011", "Customer 11", 2000),
        ("CUST012", "Customer 12", 3000),
        ("CUST013", "Customer 13", 4000),
        ("CUST014", "Customer 14", 5000),
    ]

    for cust_id, name, limit in customer_data:
        await conn.execute(
            """INSERT INTO customers (_id, name, credit_limit, _deleted)
               VALUES ($1, $2, $3, $4)""",
            cust_id,
            name,
            limit,
            False,
        )

    reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="ecommerce_pub",
        slot_name="ecommerce_slot",
        host=ecommerce_db["host"],
        database=ecommerce_db["database"],
        port=ecommerce_db["port"],
        user=ecommerce_db["user"],
        password=ecommerce_db["password"],
    )

    messages = []

    async def collect_messages():
        count = 0
        async for message in reader:
            if message is not None:
                messages.append(message)
                count += 1
                if count >= 5:
                    break

    try:
        await asyncio.wait_for(collect_messages(), timeout=10.0)
    except asyncio.TimeoutError:
        pass

    await reader.stop()

    assert len(messages) == 5

    # Verify all are INSERTs
    assert all(msg.op == "c" for msg in messages)

    # Verify all customer IDs are present
    inserted_ids = {msg.after["_id"] for msg in messages}
    expected_ids = {f"CUST01{i}" for i in range(5)}
    assert inserted_ids == expected_ids


@pytest.mark.asyncio
async def test_order_cancellation_cascade(ecommerce_db):
    """Test cascading soft deletes when cancelling an order."""
    import pgoutput_decoder

    conn = ecommerce_db["connection"]

    # Setup: customer, product, order, and order line
    await conn.execute(
        """INSERT INTO customers (_id, name, credit_limit, _deleted)
           VALUES ($1, $2, $3, $4)""",
        "CUST020",
        "Diana Prince",
        15000,
        False,
    )

    await conn.execute(
        """INSERT INTO products (_id, name, description, price, _deleted)
           VALUES ($1, $2, $3, $4, $5)""",
        "PROD020",
        "Monitor",
        "4K Monitor",
        Decimal("399.99"),
        False,
    )

    await conn.execute(
        """INSERT INTO orders (_id, cust_id, order_date, _deleted)
           VALUES ($1, $2, $3, $4)""",
        "ORD020",
        "CUST020",
        date(2026, 2, 12),
        False,
    )

    await conn.execute(
        """INSERT INTO order_lines (_id, order_id, product_id, quantity, unit_price, _deleted)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        "LINE020",
        "ORD020",
        "PROD020",
        2,
        Decimal("399.99"),
        False,
    )

    # Now soft delete the order and its lines
    await conn.execute("UPDATE orders SET _deleted = TRUE WHERE _id = $1", "ORD020")
    await conn.execute("UPDATE order_lines SET _deleted = TRUE WHERE order_id = $1", "ORD020")

    reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="ecommerce_pub",
        slot_name="ecommerce_slot",
        host=ecommerce_db["host"],
        database=ecommerce_db["database"],
        port=ecommerce_db["port"],
        user=ecommerce_db["user"],
        password=ecommerce_db["password"],
    )

    messages = []

    async def collect_messages():
        count = 0
        async for message in reader:
            if message is not None:
                messages.append(message)
                count += 1
                if count >= 6:  # 4 inserts + 2 soft delete updates
                    break

    try:
        await asyncio.wait_for(collect_messages(), timeout=10.0)
    except asyncio.TimeoutError:
        pass

    await reader.stop()

    assert len(messages) == 6

    # Find the soft delete messages
    updates = [msg for msg in messages if msg.op == "u"]
    assert len(updates) == 2

    # Verify both updates set _deleted to TRUE
    for update in updates:
        assert update.after["_deleted"] is True


@pytest.mark.asyncio
async def test_mixed_operations_single_transaction(ecommerce_db):
    """Test multiple operations in a single transaction."""
    import pgoutput_decoder

    conn = ecommerce_db["connection"]

    # Start transaction
    async with conn.transaction():
        await conn.execute(
            """INSERT INTO customers (_id, name, credit_limit, _deleted)
               VALUES ($1, $2, $3, $4)""",
            "CUST030",
            "Eve Anderson",
            8000,
            False,
        )

        await conn.execute(
            """INSERT INTO products (_id, name, description, price, _deleted)
               VALUES ($1, $2, $3, $4, $5)""",
            "PROD030",
            "Tablet",
            "10-inch tablet",
            Decimal("299.99"),
            False,
        )

        # Update customer immediately in same transaction
        await conn.execute("UPDATE customers SET credit_limit = $1 WHERE _id = $2", 9000, "CUST030")

    reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="ecommerce_pub",
        slot_name="ecommerce_slot",
        host=ecommerce_db["host"],
        database=ecommerce_db["database"],
        port=ecommerce_db["port"],
        user=ecommerce_db["user"],
        password=ecommerce_db["password"],
    )

    messages = []

    async def collect_messages():
        count = 0
        async for message in reader:
            if message is not None:
                messages.append(message)
                count += 1
                if count >= 3:
                    break

    try:
        await asyncio.wait_for(collect_messages(), timeout=10.0)
    except asyncio.TimeoutError:
        pass

    await reader.stop()

    assert len(messages) == 3

    # Verify sequence: customer INSERT, product INSERT, customer UPDATE
    assert messages[0].op == "c"
    assert messages[0].source["table"] == "customers"

    assert messages[1].op == "c"
    assert messages[1].source["table"] == "products"

    assert messages[2].op == "u"
    assert messages[2].source["table"] == "customers"
    assert messages[2].after["credit_limit"] == 9000


@pytest.mark.asyncio
async def test_null_values_in_description(ecommerce_db):
    """Test handling of NULL values in optional columns."""
    import pgoutput_decoder

    conn = ecommerce_db["connection"]

    # Insert product with NULL description
    await conn.execute(
        """INSERT INTO products (_id, name, description, price, _deleted)
           VALUES ($1, $2, $3, $4, $5)""",
        "PROD040",
        "Generic Product",
        None,
        Decimal("49.99"),
        False,
    )

    # Update to set description
    await conn.execute(
        "UPDATE products SET description = $1 WHERE _id = $2", "Now has a description", "PROD040"
    )

    # Update to set back to NULL
    await conn.execute("UPDATE products SET description = NULL WHERE _id = $1", "PROD040")

    reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="ecommerce_pub",
        slot_name="ecommerce_slot",
        host=ecommerce_db["host"],
        database=ecommerce_db["database"],
        port=ecommerce_db["port"],
        user=ecommerce_db["user"],
        password=ecommerce_db["password"],
    )

    messages = []

    async def collect_messages():
        count = 0
        async for message in reader:
            if message is not None:
                messages.append(message)
                count += 1
                if count >= 3:
                    break

    try:
        await asyncio.wait_for(collect_messages(), timeout=10.0)
    except asyncio.TimeoutError:
        pass

    await reader.stop()

    assert len(messages) == 3

    # Verify INSERT with NULL
    assert messages[0].op == "c"
    assert messages[0].after["description"] is None

    # Verify UPDATE setting value
    assert messages[1].op == "u"
    assert messages[1].after["description"] == "Now has a description"

    # Verify UPDATE back to NULL
    assert messages[2].op == "u"
    assert messages[2].after["description"] is None


@pytest.mark.asyncio
async def test_decimal_precision(ecommerce_db):
    """Test decimal value precision handling."""
    import pgoutput_decoder

    conn = ecommerce_db["connection"]

    # Insert products with various decimal values
    test_prices = [
        ("PROD050", Decimal("0.01")),  # Minimum
        ("PROD051", Decimal("99.99")),  # Two decimals
        ("PROD052", Decimal("1000.00")),  # Whole number
        ("PROD053", Decimal("12345.67")),  # Large number
    ]

    for prod_id, price in test_prices:
        await conn.execute(
            """INSERT INTO products (_id, name, description, price, _deleted)
               VALUES ($1, $2, $3, $4, $5)""",
            prod_id,
            f"Product {prod_id}",
            "Test product",
            price,
            False,
        )

    reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="ecommerce_pub",
        slot_name="ecommerce_slot",
        host=ecommerce_db["host"],
        database=ecommerce_db["database"],
        port=ecommerce_db["port"],
        user=ecommerce_db["user"],
        password=ecommerce_db["password"],
    )

    messages = []

    async def collect_messages():
        count = 0
        async for message in reader:
            if message is not None:
                messages.append(message)
                count += 1
                if count >= 4:
                    break

    try:
        await asyncio.wait_for(collect_messages(), timeout=10.0)
    except asyncio.TimeoutError:
        pass

    await reader.stop()

    assert len(messages) == 4

    # Verify all prices are correct (convert to float for comparison)
    received_prices = {msg.after["_id"]: float(msg.after["price"]) for msg in messages}

    for prod_id, expected_price in test_prices:
        assert abs(received_prices[prod_id] - float(expected_price)) < 0.01


@pytest.mark.asyncio
async def test_api_matches_specification(ecommerce_db):
    """Test that API matches the exact user specification."""
    import pgoutput_decoder

    conn = ecommerce_db["connection"]

    # Insert test data
    await conn.execute(
        """INSERT INTO customers (_id, name, credit_limit, _deleted)
           VALUES ($1, $2, $3, $4)""",
        "CUST999",
        "Test User",
        1000,
        False,
    )

    # Exact API from user's specification
    cdc_reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="ecommerce_pub",
        slot_name="ecommerce_slot",
        host=ecommerce_db["host"],
        database=ecommerce_db["database"],
        port=ecommerce_db["port"],
        user=ecommerce_db["user"],
        password=ecommerce_db["password"],
    )

    # Use exact API pattern from specification
    message_count = 0
    async for message in cdc_reader:
        if message is not None:
            # Test json() method with indent parameter as specified
            json_output = message.json(indent=2)
            assert isinstance(json_output, str)
            assert len(json_output) > 0

            message_count += 1
            if message_count >= 1:
                break

    # Use stop() method as specified
    await cdc_reader.stop()

    assert message_count >= 1
