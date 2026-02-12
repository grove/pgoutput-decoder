"""
Simple Synchronous CDC Consumer using asyncio.run()

This example shows how to consume CDC messages in a synchronous-style application
using asyncio.run() to wrap the async API. This is ideal for:

- Simple scripts and CLI tools
- Batch processing jobs
- Applications that can block on CDC messages

NOTE: This pattern blocks the entire process while consuming messages.
For long-running applications that need to do other work, see background_thread.py instead.

Prerequisites:
    - PostgreSQL 12+ with wal_level=logical
    - A publication: CREATE PUBLICATION my_pub FOR ALL TABLES;
    - A replication slot (created automatically on first connection)

Usage:
    python sync_wrapper.py
"""

import asyncio
from typing import Callable, Optional

import pgoutput_decoder
from pgoutput_decoder import ReplicationMessage, format_operation, get_table_name


def consume_cdc_messages(
    publication_name: str,
    slot_name: str,
    host: str,
    database: str,
    port: int,
    user: str,
    password: str,
    callback: Callable[[ReplicationMessage], None],
    max_messages: Optional[int] = None,
) -> None:
    """
    Consume CDC messages synchronously.

    This function wraps the async CDC reader in asyncio.run(), making it
    appear synchronous to the caller. Perfect for simple scripts.

    Args:
        publication_name: PostgreSQL publication name (e.g., 'my_publication')
        slot_name: Replication slot name (e.g., 'my_slot')
        host: PostgreSQL host (e.g., 'localhost')
        database: Database name (e.g., 'mydb')
        port: PostgreSQL port (default: 5432)
        user: Database username
        password: Database password
        callback: Function called for each CDC message
        max_messages: Stop after N messages (None = run forever)

    Example:
        def handle_change(message):
            print(f"Change detected: {message.op}")

        consume_cdc_messages(
            publication_name="my_pub",
            slot_name="my_slot",
            host="localhost",
            database="mydb",
            port=5432,
            user="postgres",
            password="secret",
            callback=handle_change,
            max_messages=10  # Process 10 messages then exit
        )
    """

    async def _async_consume() -> None:
        """Internal async function that does the actual work."""
        # Create the CDC reader
        reader = pgoutput_decoder.LogicalReplicationReader(
            publication_name=publication_name,
            slot_name=slot_name,
            host=host,
            database=database,
            port=port,
            user=user,
            password=password,
        )

        message_count = 0
        try:
            # Iterate over CDC messages
            async for message in reader:
                if message is not None:
                    # Call user's callback function
                    callback(message)
                    message_count += 1

                    # Stop if we've reached the limit
                    if max_messages and message_count >= max_messages:
                        print(f"\nProcessed {message_count} messages. Stopping.")
                        break
        finally:
            # Always clean up the reader
            await reader.stop()

    # Run the async function in a new event loop
    asyncio.run(_async_consume())


def simple_message_handler(message: ReplicationMessage) -> None:
    """
    Example callback function that prints message details.

    This is called for each CDC message received. Customize this
    to implement your own business logic.

    Args:
        message: CDC message with before/after data and metadata
    """
    operation = format_operation(message.op)  # "INSERT", "UPDATE", "DELETE"
    table = get_table_name(message)  # e.g., "public.customers"

    print(f"\n{'=' * 60}")
    print(f"Operation: {operation}")
    print(f"Table: {table}")
    print(f"Timestamp: {message.ts_ms}ms")

    # Show the data that changed
    if message.op in ("c", "r"):  # CREATE or READ (snapshot)
        print(f"New data: {message.after}")
    elif message.op == "u":  # UPDATE
        print(f"Before: {message.before}")
        print(f"After: {message.after}")
    elif message.op == "d":  # DELETE
        print(f"Deleted: {message.before}")


def custom_message_handler(message: ReplicationMessage) -> None:
    """
    Advanced example: Filter and process specific tables.

    This shows how to implement business logic based on the
    table name and operation type.
    """
    table = get_table_name(message)

    # Only process certain tables
    if table == "public.orders":
        if message.op == "c":  # New order
            order_data = message.after
            print(f"💰 New order created: {order_data}")
            # TODO: Send notification, update inventory, etc.

        elif message.op == "u":  # Order updated
            print(f"📝 Order updated: {message.after}")
            # TODO: Handle status changes, etc.

    elif table == "public.customers":
        if message.op == "c":
            print(f"👤 New customer: {message.after}")
            # TODO: Send welcome email, etc.


# ============================================================================
# Main execution examples
# ============================================================================


def example_simple():
    """Example 1: Simple message printing."""
    print("Example 1: Simple CDC Consumer")
    print("Processing up to 5 messages...\n")

    consume_cdc_messages(
        publication_name="ecommerce_pub",
        slot_name="simple_example_slot",
        host="localhost",
        database="ecommerce_db",
        port=5432,
        user="postgres",
        password="password",
        callback=simple_message_handler,
        max_messages=5,  # Stop after 5 messages
    )


def example_continuous():
    """Example 2: Continuous monitoring (Ctrl+C to stop)."""
    print("Example 2: Continuous CDC Monitoring")
    print("Press Ctrl+C to stop...\n")

    try:
        consume_cdc_messages(
            publication_name="ecommerce_pub",
            slot_name="continuous_example_slot",
            host="localhost",
            database="ecommerce_db",
            port=5432,
            user="postgres",
            password="password",
            callback=simple_message_handler,
            max_messages=None,  # Run forever
        )
    except KeyboardInterrupt:
        print("\n\nStopped by user.")


def example_custom_logic():
    """Example 3: Custom business logic."""
    print("Example 3: Custom Business Logic")
    print("Processing orders and customers only...\n")

    consume_cdc_messages(
        publication_name="ecommerce_pub",
        slot_name="custom_logic_slot",
        host="localhost",
        database="ecommerce_db",
        port=5432,
        user="postgres",
        password="password",
        callback=custom_message_handler,
        max_messages=10,
    )


if __name__ == "__main__":
    # Uncomment the example you want to run:

    example_simple()  # Quick test - processes 5 messages
    # example_continuous()  # Runs forever until Ctrl+C
    # example_custom_logic()  # Shows table-specific logic
