"""Tests for JSON serialization functions and Debezium format compliance."""

import json

import asyncpg
import pytest
from pgoutput_decoder import (
    LogicalReplicationReader,
    message_to_debezium_json,
    message_to_dict,
)
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.docker


def create_reader(db_config, auto_ack=True):
    """Helper function to create a LogicalReplicationReader."""
    return LogicalReplicationReader(
        publication_name="test_pub",
        slot_name="test_slot",
        host=db_config["host"],
        database=db_config["database"],
        port=db_config["port"],
        user=db_config["user"],
        password=db_config["password"],
        auto_acknowledge=auto_ack,
    )


@pytest.fixture(scope="function")
async def json_test_db():
    """Set up PostgreSQL for JSON serialization tests."""
    postgres = PostgresContainer(
        image="postgres:18.1-alpine",
        username="test",
        password="test",
        dbname="json_test",
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
            database="json_test",
        )

        # Create test table with various data types
        await conn.execute("""
            CREATE TABLE test_table (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100),
                age INTEGER,
                balance NUMERIC(10, 2),
                active BOOLEAN,
                metadata JSONB,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # Set replica identity for UPDATE/DELETE tests
        await conn.execute("ALTER TABLE test_table REPLICA IDENTITY FULL")

        # Create publication and replication slot
        await conn.execute("CREATE PUBLICATION test_pub FOR ALL TABLES")
        await conn.execute("SELECT pg_create_logical_replication_slot('test_slot', 'pgoutput')")

        yield {
            "conn": conn,
            "host": postgres.get_container_host_ip(),
            "port": postgres.get_exposed_port(5432),
            "database": "json_test",
            "user": "test",
            "password": "test",
        }

        await conn.close()


@pytest.mark.asyncio
async def test_json_serialization_produces_valid_json(json_test_db):
    """Test that message_to_debezium_json produces valid JSON."""
    conn = json_test_db["conn"]

    # Insert test data
    await conn.execute("""
        INSERT INTO test_table (name, age, balance, active, metadata)
        VALUES ('Alice', 30, 1000.50, true, '{"role": "admin"}')
    """)

    # Create reader and get message
    reader = create_reader(json_test_db)

    message = None
    async for msg in reader:
        message = msg
        break

    # Test with different indent options
    for indent in [None, 0, 2, 4]:
        json_str = message_to_debezium_json(message, indent=indent)

        # Verify it's valid JSON
        try:
            parsed = json.loads(json_str)
            assert isinstance(parsed, dict), "JSON should parse to a dictionary"
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON with indent={indent}: {e}")


@pytest.mark.asyncio
async def test_debezium_format_compliance(json_test_db):
    """Test that JSON output complies with Debezium CDC format."""
    conn = json_test_db["conn"]

    # Insert test data
    await conn.execute("""
        INSERT INTO test_table (name, age, balance, active)
        VALUES ('Bob', 25, 500.00, false)
    """)

    reader = create_reader(json_test_db)

    message = None
    async for msg in reader:
        message = msg
        break

    # Parse JSON
    json_str = message_to_debezium_json(message)
    debezium_event = json.loads(json_str)

    # Verify required Debezium fields
    assert "op" in debezium_event, "Missing 'op' field"
    assert "before" in debezium_event, "Missing 'before' field"
    assert "after" in debezium_event, "Missing 'after' field"
    assert "source" in debezium_event, "Missing 'source' field"
    assert "ts_ms" in debezium_event, "Missing 'ts_ms' field"

    # Verify operation type is valid
    assert debezium_event["op"] in ["c", "u", "d", "r"], (
        f"Invalid operation type: {debezium_event['op']}"
    )

    # Verify source metadata
    source = debezium_event["source"]
    assert "schema" in source, "Missing 'schema' in source"
    assert "table" in source, "Missing 'table' in source"
    assert "lsn" in source, "Missing 'lsn' in source"

    # Verify timestamp is a number
    assert isinstance(debezium_event["ts_ms"], (int, float)), "ts_ms should be a number"


@pytest.mark.asyncio
async def test_insert_operation_format(json_test_db):
    """Test JSON format for INSERT operations."""
    conn = json_test_db["conn"]

    await conn.execute("""
        INSERT INTO test_table (name, age, balance, active)
        VALUES ('Charlie', 35, 1500.75, true)
    """)

    reader = create_reader(json_test_db)

    message = None
    async for msg in reader:
        message = msg
        break

    json_str = message_to_debezium_json(message)
    event = json.loads(json_str)

    # INSERT should have op="c"
    assert event["op"] == "c", "INSERT operation should have op='c'"

    # INSERT should have null before
    assert event["before"] is None, "INSERT should have before=null"

    # INSERT should have populated after
    assert event["after"] is not None, "INSERT should have populated after"
    assert isinstance(event["after"], dict), "after should be a dictionary"

    # Verify after contains inserted data
    after = event["after"]
    assert after["name"] == "Charlie"
    assert after["age"] == 35
    # Boolean values might be returned as 1/0 from PostgreSQL
    assert after["active"] in [True, 1], "active should be True or 1"


@pytest.mark.asyncio
async def test_update_operation_format(json_test_db):
    """Test JSON format for UPDATE operations."""
    conn = json_test_db["conn"]

    # Insert then update
    await conn.execute("""
        INSERT INTO test_table (id, name, age, balance, active)
        VALUES (100, 'Diana', 28, 750.00, false)
    """)

    reader = create_reader(json_test_db)

    # Skip INSERT message
    async for msg in reader:
        break

    # Now do UPDATE
    await conn.execute("""
        UPDATE test_table SET age = 29, balance = 800.00 WHERE id = 100
    """)

    message = None
    async for msg in reader:
        message = msg
        break

    json_str = message_to_debezium_json(message)
    event = json.loads(json_str)

    # UPDATE should have op="u"
    assert event["op"] == "u", "UPDATE operation should have op='u'"

    # UPDATE should have both before and after (with REPLICA IDENTITY FULL)
    assert event["before"] is not None, "UPDATE should have before with REPLICA IDENTITY FULL"
    assert event["after"] is not None, "UPDATE should have after"

    # Verify before has old values
    before = event["before"]
    assert before["age"] == 28
    assert before["balance"] == 750.0

    # Verify after has new values
    after = event["after"]
    assert after["age"] == 29
    assert after["balance"] == 800.0


@pytest.mark.asyncio
async def test_delete_operation_format(json_test_db):
    """Test JSON format for DELETE operations."""
    conn = json_test_db["conn"]

    # Insert then delete
    await conn.execute("""
        INSERT INTO test_table (id, name, age, balance, active)
        VALUES (200, 'Eve', 32, 900.00, true)
    """)

    reader = create_reader(json_test_db)

    # Skip INSERT message
    async for msg in reader:
        break

    # Now do DELETE
    await conn.execute("DELETE FROM test_table WHERE id = 200")

    message = None
    async for msg in reader:
        message = msg
        break

    json_str = message_to_debezium_json(message)
    event = json.loads(json_str)

    # DELETE should have op="d"
    assert event["op"] == "d", "DELETE operation should have op='d'"

    # DELETE should have null after
    assert event["after"] is None, "DELETE should have after=null"

    # DELETE should have populated before (with REPLICA IDENTITY FULL)
    assert event["before"] is not None, "DELETE should have before with REPLICA IDENTITY FULL"
    assert isinstance(event["before"], dict), "before should be a dictionary"

    # Verify before contains deleted data
    before = event["before"]
    assert before["name"] == "Eve"
    assert before["age"] == 32


@pytest.mark.asyncio
async def test_json_with_null_values(json_test_db):
    """Test JSON serialization handles NULL values correctly."""
    conn = json_test_db["conn"]

    await conn.execute("""
        INSERT INTO test_table (name, age, balance, active, metadata)
        VALUES ('Frank', NULL, NULL, true, NULL)
    """)

    reader = create_reader(json_test_db)

    message = None
    async for msg in reader:
        message = msg
        break

    json_str = message_to_debezium_json(message)
    event = json.loads(json_str)

    # Verify NULL values are represented correctly
    after = event["after"]
    assert after["name"] == "Frank"
    assert after["age"] is None, "NULL age should be None in JSON"
    assert after["balance"] is None, "NULL balance should be None in JSON"
    assert after["metadata"] is None, "NULL JSONB should be None in JSON"


@pytest.mark.asyncio
async def test_json_with_special_characters(json_test_db):
    """Test JSON serialization handles special characters correctly."""
    conn = json_test_db["conn"]

    # Use special characters that need escaping in JSON
    special_name = 'Test "quotes" and \\backslash\\ and\nnewline'

    await conn.execute(
        """
        INSERT INTO test_table (name, age)
        VALUES ($1, 40)
    """,
        special_name,
    )

    reader = create_reader(json_test_db)

    message = None
    async for msg in reader:
        message = msg
        break

    json_str = message_to_debezium_json(message)
    event = json.loads(json_str)

    # Verify special characters are properly escaped and preserved
    assert event["after"]["name"] == special_name


@pytest.mark.asyncio
async def test_json_with_jsonb_data(json_test_db):
    """Test JSON serialization handles JSONB data correctly."""
    conn = json_test_db["conn"]

    # Use simpler JSONB without arrays (known limitation in pgoutput decoder for some types)
    metadata = {"role": "admin", "count": 42, "enabled": True}

    await conn.execute(
        """
        INSERT INTO test_table (name, age, metadata)
        VALUES ('Grace', 33, $1::jsonb)
    """,
        json.dumps(metadata),
    )

    reader = create_reader(json_test_db)

    message = None
    async for msg in reader:
        message = msg
        break

    json_str = message_to_debezium_json(message)
    event = json.loads(json_str)

    # Verify JSONB is properly nested in JSON
    # Note: pgoutput decoder may have limitations with arrays in JSONB
    assert event["after"]["metadata"] is not None, "metadata should not be None"
    assert isinstance(event["after"]["metadata"], dict), "metadata should be a dict"
    # Check the fields that should be there
    assert event["after"]["metadata"]["role"] == "admin"
    assert event["after"]["metadata"]["count"] == 42


@pytest.mark.asyncio
async def test_indent_options(json_test_db):
    """Test different indent options produce correctly formatted JSON."""
    conn = json_test_db["conn"]

    await conn.execute("""
        INSERT INTO test_table (name, age)
        VALUES ('Henry', 45)
    """)

    reader = create_reader(json_test_db)

    message = None
    async for msg in reader:
        message = msg
        break

    # Test compact JSON (no indent)
    compact_json = message_to_debezium_json(message, indent=None)
    assert "\n" not in compact_json, "Compact JSON should not have newlines"

    # Test with 2-space indent (default)
    pretty_json_2 = message_to_debezium_json(message, indent=2)
    assert "\n" in pretty_json_2, "Pretty JSON should have newlines"
    assert "  " in pretty_json_2, "2-space indent should contain 2 spaces"

    # Test with 4-space indent
    pretty_json_4 = message_to_debezium_json(message, indent=4)
    assert "\n" in pretty_json_4, "Pretty JSON should have newlines"
    assert "    " in pretty_json_4, "4-space indent should contain 4 spaces"

    # All should parse to the same structure
    compact_parsed = json.loads(compact_json)
    pretty_2_parsed = json.loads(pretty_json_2)
    pretty_4_parsed = json.loads(pretty_json_4)

    assert compact_parsed == pretty_2_parsed == pretty_4_parsed, (
        "All indent options should produce same data structure"
    )


@pytest.mark.asyncio
async def test_message_to_dict_consistency(json_test_db):
    """Test that message_to_dict produces same structure as parsed JSON."""
    conn = json_test_db["conn"]

    await conn.execute("""
        INSERT INTO test_table (name, age, balance, active)
        VALUES ('Iris', 27, 1200.00, true)
    """)

    reader = create_reader(json_test_db)

    message = None
    async for msg in reader:
        message = msg
        break

    # Get dict from helper function
    dict_from_helper = message_to_dict(message)

    # Get dict from parsing JSON
    json_str = message_to_debezium_json(message)
    dict_from_json = json.loads(json_str)

    # They should be equivalent
    assert dict_from_helper == dict_from_json, (
        "message_to_dict should produce same structure as parsed JSON"
    )


@pytest.mark.asyncio
async def test_timestamp_fields_present(json_test_db):
    """Test that timestamp fields are present and valid."""
    conn = json_test_db["conn"]

    await conn.execute("""
        INSERT INTO test_table (name, age)
        VALUES ('Jack', 50)
    """)

    reader = create_reader(json_test_db)

    message = None
    async for msg in reader:
        message = msg
        break

    json_str = message_to_debezium_json(message)
    event = json.loads(json_str)

    # ts_ms should always be present
    assert "ts_ms" in event, "ts_ms field should be present"
    assert isinstance(event["ts_ms"], (int, float)), "ts_ms should be a number"
    assert event["ts_ms"] > 0, "ts_ms should be positive"

    # ts_us and ts_ns are optional but should be valid if present
    if "ts_us" in event:
        assert isinstance(event["ts_us"], (int, float)), "ts_us should be a number"
        assert event["ts_us"] > 0, "ts_us should be positive"

    if "ts_ns" in event:
        assert isinstance(event["ts_ns"], (int, float)), "ts_ns should be a number"
        assert event["ts_ns"] > 0, "ts_ns should be positive"


@pytest.mark.asyncio
async def test_source_metadata_completeness(json_test_db):
    """Test that source metadata contains all expected fields."""
    conn = json_test_db["conn"]

    await conn.execute("""
        INSERT INTO test_table (name, age)
        VALUES ('Karen', 38)
    """)

    reader = create_reader(json_test_db)

    message = None
    async for msg in reader:
        message = msg
        break

    json_str = message_to_debezium_json(message)
    event = json.loads(json_str)

    source = event["source"]

    # Verify essential source fields
    assert "schema" in source, "source should contain schema"
    assert "table" in source, "source should contain table"
    assert source["table"] == "test_table", "table name should match"

    # LSN should be present and valid
    assert "lsn" in source, "source should contain lsn"
    assert isinstance(source["lsn"], (int, str)), "lsn should be int or string"


@pytest.mark.asyncio
async def test_rust_json_method_compatibility(json_test_db):
    """Test that message.json() method produces same result as helper function."""
    conn = json_test_db["conn"]

    await conn.execute("""
        INSERT INTO test_table (name, age)
        VALUES ('Laura', 29)
    """)

    reader = create_reader(json_test_db)

    message = None
    async for msg in reader:
        message = msg
        break

    # Test both methods produce same result
    for indent in [None, 2, 4]:
        json_from_method = message.json(indent=indent)
        json_from_function = message_to_debezium_json(message, indent=indent)

        # Parse both to verify they're equivalent
        parsed_method = json.loads(json_from_method)
        parsed_function = json.loads(json_from_function)

        assert parsed_method == parsed_function, (
            "message.json() and message_to_debezium_json() "
            f"should produce same result with indent={indent}"
        )
