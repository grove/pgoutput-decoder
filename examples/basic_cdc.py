"""
Basic CDC (Change Data Capture) example using pgoutput-decoder with e-commerce schema.

This example demonstrates using helper functions to format CDC messages.
"""

import asyncio

import pgoutput_decoder
from pgoutput_decoder import format_operation, get_table_name, message_to_debezium_json


async def main():
    """Main function demonstrating basic CDC usage with e-commerce schema."""

    # Configuration (update with your PostgreSQL details)
    host = "localhost"
    database_name = "ecommerce_db"
    port = 5432
    user = "postgres"
    password = "password"

    # Create logical replication reader
    cdc_reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="ecommerce_pub",
        slot_name="ecommerce_slot",
        host=host,
        database=database_name,
        port=port,
        user=user,
        password=password,
    )

    print("Starting CDC stream for e-commerce database...")
    print("Monitoring tables: customers, orders, products, order_lines")
    print("Press Ctrl+C to stop\n")

    try:
        # Consume messages using async for loop
        async for message in cdc_reader:
            if message is not None:
                # Print formatted operation and table
                print(f"{format_operation(message.op)} on {get_table_name(message)}")

                # Print message as JSON using helper function
                print(message_to_debezium_json(message, indent=2))
                print("-" * 80)
    except KeyboardInterrupt:
        print("\nStopping CDC stream...")
    finally:
        # Stop the reader
        await cdc_reader.stop()
        print("CDC stream stopped.")


if __name__ == "__main__":
    asyncio.run(main())
