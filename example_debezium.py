"""
Example demonstrating the new Debezium-compatible message format.

Run this after setting up the test database with:
    uv run pytest tests/test_ecommerce_comprehensive.py::test_customer_crud_operations
"""

import asyncio

import pgoutput_decoder
from pgoutput_decoder import format_operation, get_table_name, message_to_debezium_json


async def demo_debezium_format():
    """Demonstrate Debezium-compatible message format."""

    # Example with auto_acknowledge=True (default)
    reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="ecommerce_pub",
        slot_name="ecommerce_slot",
        host="localhost",
        database="ecommerce",
        port=5432,
        user="geir.gronmo",
        password="",
        auto_acknowledge=True,  # LSN acknowledged automatically
    )

    async for message in reader:
        if message is not None:
            # Use helper function to convert to JSON
            print(f"\n{format_operation(message.op)} on {get_table_name(message)}")
            print(message_to_debezium_json(message, indent=2))
            break

    await reader.stop()


async def demo_manual_acknowledge():
    """Demonstrate manual LSN acknowledgment."""

    # Example with auto_acknowledge=False (manual control)
    reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="ecommerce_pub",
        slot_name="ecommerce_slot",
        host="localhost",
        database="ecommerce",
        port=5432,
        user="geir.gronmo",
        password="",
        auto_acknowledge=False,  # Manual LSN control
    )

    messages_processed = 0

    async for message in reader:
        if message is not None:
            op = format_operation(message.op)
            table = get_table_name(message)
            print(f"\nProcessing message {messages_processed + 1}: {op} on {table}")
            print(message_to_debezium_json(message, indent=None))  # Compact JSON

            messages_processed += 1

            # Manually acknowledge when ready
            await reader.acknowledge()
            print(f"  ✓ Acknowledged LSN: {message.source['lsn']}")

            if messages_processed >= 3:
                break

    await reader.stop()
    print(f"\nTotal messages processed: {messages_processed}")


if __name__ == "__main__":
    print("=" * 60)
    print("Debezium Format Example")
    print("=" * 60)

    try:
        asyncio.run(demo_debezium_format())
    except Exception as e:
        print(f"Error: {e}")
        print("\nNote: This example requires a running PostgreSQL with")
        print("      the ecommerce database and test data.")
        print("      Run the test suite first to set this up.")

    print("\n" + "=" * 60)
    print("Manual Acknowledgment Example")
    print("=" * 60)

    try:
        asyncio.run(demo_manual_acknowledge())
    except Exception as e:
        print(f"Error: {e}")
