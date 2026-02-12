"""Pytest configuration and fixtures for pgoutput-decoder tests."""

import pytest
import asyncio
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for the entire test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def postgres_container():
    """PostgreSQL 18.1 container with logical replication enabled."""
    postgres = PostgresContainer(
        image="postgres:18.1-alpine",
        username="test",
        password="test",
        dbname="testdb",
    )
    # Configure for logical replication before starting
    postgres.with_command(
        "postgres "
        "-c wal_level=logical "
        "-c max_replication_slots=4 "
        "-c max_wal_senders=4"
    )
    
    with postgres:
        yield postgres


@pytest.fixture
async def postgres_with_ecommerce_schema(postgres_container):
    """PostgreSQL container with e-commerce schema and replication configured."""
    import asyncpg
    
    # Connect and set up replication
    conn = await asyncpg.connect(
        host=postgres_container.get_container_host_ip(),
        port=postgres_container.get_exposed_port(5432),
        user="test",
        password="test",
        database="testdb",
    )
    
    try:
        # Create customers table
        await conn.execute("""
            CREATE TABLE customers (
                _id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                credit_limit INTEGER NOT NULL,
                _deleted BOOLEAN DEFAULT FALSE
            )
        """)
        
        # Create orders table
        await conn.execute("""
            CREATE TABLE orders (
                _id VARCHAR PRIMARY KEY,
                cust_id VARCHAR NOT NULL,
                order_date DATE NOT NULL,
                _deleted BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (cust_id) REFERENCES customers(_id)
            )
        """)
        
        # Create products table
        await conn.execute("""
            CREATE TABLE products (
                _id VARCHAR PRIMARY KEY,
                name VARCHAR NOT NULL,
                description VARCHAR,
                price DECIMAL(10,2) NOT NULL,
                _deleted BOOLEAN DEFAULT FALSE
            )
        """)
        
        # Create order_lines table
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
        
        # Set replica identity to FULL for all tables to capture old values
        await conn.execute("ALTER TABLE customers REPLICA IDENTITY FULL")
        await conn.execute("ALTER TABLE orders REPLICA IDENTITY FULL")
        await conn.execute("ALTER TABLE products REPLICA IDENTITY FULL")
        await conn.execute("ALTER TABLE order_lines REPLICA IDENTITY FULL")
        
        # Create publication for all tables
        await conn.execute("DROP PUBLICATION IF EXISTS ecommerce_pub CASCADE")
        await conn.execute("CREATE PUBLICATION ecommerce_pub FOR ALL TABLES")
        
        # Create replication slot
        try:
            await conn.execute(
                "SELECT pg_drop_replication_slot('ecommerce_slot')"
            )
        except Exception:
            pass  # Slot doesn't exist, that's fine
        
        result = await conn.fetchrow(
            "SELECT lsn::text FROM pg_create_logical_replication_slot('ecommerce_slot', 'pgoutput')"
        )
        start_lsn = result['lsn'] if result and result['lsn'] else '0/0'
        
        yield {
            "host": postgres_container.get_container_host_ip(),
            "port": postgres_container.get_exposed_port(5432),
            "database": "testdb",
            "user": "test",
            "password": "test",
            "connection": conn,
            "start_lsn": start_lsn,
        }
        
    finally:
        await conn.close()
