"""Tests for manual LSN acknowledgement functionality."""

import asyncio

import asyncpg
import pytest
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.docker


@pytest.fixture(scope="function")
async def pg_with_slot():
    """Create a PostgreSQL instance with replication slot and test data."""
    postgres = PostgresContainer(
        image="postgres:18.1-alpine",
        username="test",
        password="test",
        dbname="testdb",
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
            database="testdb",
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

        await conn.execute("ALTER TABLE customers REPLICA IDENTITY FULL")
        await conn.execute("CREATE PUBLICATION test_pub FOR ALL TABLES")
        await conn.execute("SELECT pg_create_logical_replication_slot('test_slot', 'pgoutput')")

        # Insert initial test data
        await conn.execute(
            "INSERT INTO customers (_id, name, credit_limit) VALUES ('C1', 'Alice', 5000)"
        )

        yield {
            "host": postgres.get_container_host_ip(),
            "port": postgres.get_exposed_port(5432),
            "database": "testdb",
            "user": "test",
            "password": "test",
            "conn": conn,
        }

        await conn.close()


@pytest.mark.asyncio
async def test_manual_acknowledgement_basic(pg_with_slot):
    """Test basic manual acknowledgement flow."""
    import pgoutput_decoder

    config = pg_with_slot

    # Create reader with manual acknowledgement
    reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="test_pub",
        slot_name="test_slot",
        host=config["host"],
        port=config["port"],
        database=config["database"],
        user=config["user"],
        password=config["password"],
        auto_acknowledge=False,  # Manual mode
    )

    messages = []

    async def collect_messages():
        async for message in reader:
            if message is not None and message.op == "c":
                messages.append(message)

                # Manually acknowledge
                await reader.acknowledge()
                break

    try:
        await asyncio.wait_for(collect_messages(), timeout=5.0)
    except asyncio.TimeoutError:
        pass

    await reader.stop()

    assert len(messages) == 1
    assert messages[0].after["_id"] == "C1"


@pytest.mark.asyncio
async def test_lsn_not_advanced_without_acknowledge(pg_with_slot):
    """Test that LSN doesn't advance without calling acknowledge()."""
    import pgoutput_decoder

    config = pg_with_slot

    # First reader: receive message but DON'T acknowledge
    reader1 = pgoutput_decoder.LogicalReplicationReader(
        publication_name="test_pub",
        slot_name="test_slot",
        host=config["host"],
        port=config["port"],
        database=config["database"],
        user=config["user"],
        password=config["password"],
        auto_acknowledge=False,
    )

    first_lsn = None

    async def collect_first():
        nonlocal first_lsn
        async for message in reader1:
            if message is not None and message.op == "c":
                first_lsn = message.source["lsn"]
                # DON'T call acknowledge()
                break

    try:
        await asyncio.wait_for(collect_first(), timeout=5.0)
    except asyncio.TimeoutError:
        pass

    await reader1.stop()

    # Second reader: should receive the SAME message
    reader2 = pgoutput_decoder.LogicalReplicationReader(
        publication_name="test_pub",
        slot_name="test_slot",
        host=config["host"],
        port=config["port"],
        database=config["database"],
        user=config["user"],
        password=config["password"],
        auto_acknowledge=False,
    )

    second_lsn = None

    async def collect_second():
        nonlocal second_lsn
        async for message in reader2:
            if message is not None and message.op == "c":
                second_lsn = message.source["lsn"]
                await reader2.acknowledge()  # Now acknowledge
                break

    try:
        await asyncio.wait_for(collect_second(), timeout=5.0)
    except asyncio.TimeoutError:
        pass

    await reader2.stop()

    # Both readers should see the same message at the same LSN
    assert first_lsn == second_lsn
    assert first_lsn is not None


@pytest.mark.asyncio
async def test_auto_vs_manual_acknowledgement(pg_with_slot):
    """Compare auto vs manual acknowledgement behavior."""
    import pgoutput_decoder

    config = pg_with_slot

    # TEST: Manual mode - messages should be replayed if not acknowledged
    reader_manual = pgoutput_decoder.LogicalReplicationReader(
        publication_name="test_pub",
        slot_name="test_slot",
        host=config["host"],
        port=config["port"],
        database=config["database"],
        user=config["user"],
        password=config["password"],
        auto_acknowledge=False,  # Manual mode - don't acknowledge
    )

    manual_messages = []

    async def collect_manual():
        async for message in reader_manual:
            if message is not None and message.op == "c":
                manual_messages.append(message)
                # DON'T acknowledge
                break

    try:
        await asyncio.wait_for(collect_manual(), timeout=5.0)
    except asyncio.TimeoutError:
        pass

    await reader_manual.stop()

    # Should see C1
    assert len(manual_messages) == 1
    assert manual_messages[0].after["_id"] == "C1"

    # Because we didn't acknowledge, the same message should appear again
    reader_manual2 = pgoutput_decoder.LogicalReplicationReader(
        publication_name="test_pub",
        slot_name="test_slot",
        host=config["host"],
        port=config["port"],
        database=config["database"],
        user=config["user"],
        password=config["password"],
        auto_acknowledge=False,
    )

    manual_messages2 = []

    async def collect_manual2():
        async for message in reader_manual2:
            if message is not None and message.op == "c":
                manual_messages2.append(message)
                # This time acknowledge
                await reader_manual2.acknowledge()
                break

    try:
        await asyncio.wait_for(collect_manual2(), timeout=5.0)
    except asyncio.TimeoutError:
        pass

    await reader_manual2.stop()

    # Should see the SAME message (C1) again because we didn't acknowledge before
    assert len(manual_messages2) == 1
    assert manual_messages2[0].after["_id"] == "C1"


@pytest.mark.asyncio
async def test_acknowledge_multiple_messages(pg_with_slot):
    """Test acknowledging after processing multiple messages."""
    import pgoutput_decoder

    config = pg_with_slot

    # Insert multiple customers
    await config["conn"].execute("""
        INSERT INTO customers (_id, name, credit_limit) VALUES
        ('C2', 'Bob', 10000),
        ('C3', 'Carol', 7500),
        ('C4', 'Dave', 3000)
    """)

    reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="test_pub",
        slot_name="test_slot",
        host=config["host"],
        port=config["port"],
        database=config["database"],
        user=config["user"],
        password=config["password"],
        auto_acknowledge=False,
    )

    messages = []

    async def collect_messages():
        async for message in reader:
            if message is not None and message.op == "c":
                messages.append(message)

                # Acknowledge after every 2 messages
                if len(messages) % 2 == 0:
                    await reader.acknowledge()

                if len(messages) >= 4:
                    break

    try:
        await asyncio.wait_for(collect_messages(), timeout=10.0)
    except asyncio.TimeoutError:
        pass

    await reader.stop()

    assert len(messages) == 4
    assert messages[0].after["_id"] == "C1"
    assert messages[1].after["_id"] == "C2"
    assert messages[2].after["_id"] == "C3"
    assert messages[3].after["_id"] == "C4"


@pytest.mark.asyncio
async def test_acknowledge_in_auto_mode_fails_gracefully(pg_with_slot):
    """Test that calling acknowledge() in auto mode raises appropriate error."""
    import pgoutput_decoder

    config = pg_with_slot

    reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="test_pub",
        slot_name="test_slot",
        host=config["host"],
        port=config["port"],
        database=config["database"],
        user=config["user"],
        password=config["password"],
        auto_acknowledge=True,  # Auto mode
    )

    error_message = None

    async def collect_with_ack():
        nonlocal error_message
        try:
            async for message in reader:
                if message is not None and message.op == "c":
                    # In auto mode, pending_lsn is None, so this should raise an error
                    await reader.acknowledge()
                    break
        except Exception as e:
            error_message = str(e)

    try:
        await asyncio.wait_for(collect_with_ack(), timeout=5.0)
    except asyncio.TimeoutError:
        pass

    await reader.stop()

    # Should get an error about no pending LSN
    assert error_message is not None
    assert "No pending LSN" in error_message


@pytest.mark.asyncio
async def test_default_is_auto_acknowledge(pg_with_slot):
    """Test that default behavior is auto_acknowledge=True."""
    import pgoutput_decoder

    config = pg_with_slot

    # Create reader WITHOUT specifying auto_acknowledge (should default to True)
    reader1 = pgoutput_decoder.LogicalReplicationReader(
        publication_name="test_pub",
        slot_name="test_slot",
        host=config["host"],
        port=config["port"],
        database=config["database"],
        user=config["user"],
        password=config["password"],
        # auto_acknowledge not specified - should default to True
    )

    messages1 = []

    async def collect_first():
        async for message in reader1:
            if message is not None and message.op == "c":
                messages1.append(message)
                break

    try:
        await asyncio.wait_for(collect_first(), timeout=5.0)
    except asyncio.TimeoutError:
        pass

    await reader1.stop()

    assert len(messages1) == 1
    assert messages1[0].after["_id"] == "C1"

    # Try to call acknowledge() - should fail because auto mode has no pending LSN
    reader2 = pgoutput_decoder.LogicalReplicationReader(
        publication_name="test_pub",
        slot_name="test_slot",
        host=config["host"],
        port=config["port"],
        database=config["database"],
        user=config["user"],
        password=config["password"],
        # auto_acknowledge not specified - defaults to True
    )

    error_message = None

    async def test_acknowledge_fails():
        nonlocal error_message
        try:
            async for message in reader2:
                if message is not None and message.op == "c":
                    # Should fail because auto mode doesn't have pending LSN
                    await reader2.acknowledge()
                    break
        except Exception as e:
            error_message = str(e)

    try:
        await asyncio.wait_for(test_acknowledge_fails(), timeout=5.0)
    except asyncio.TimeoutError:
        pass

    await reader2.stop()

    # Default is auto mode, so acknowledge() should fail
    assert error_message is not None
    assert "No pending LSN" in error_message
