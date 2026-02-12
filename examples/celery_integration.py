"""
Celery Integration for Distributed CDC Processing

This example shows how to distribute CDC message processing across multiple
Celery workers. This is ideal for:

- Distributed systems that need horizontal scaling
- Long-running or CPU-intensive message processing
- Fault-tolerant CDC workflows with retries
- Microservices architectures

Prerequisites:
    - PostgreSQL 12+ with wal_level=logical
    - Redis or RabbitMQ (Celery broker)
    - Celery installed: pip install celery redis

Architecture:
    ┌─────────────┐       ┌──────────────┐       ┌───────────────┐
    │ PostgreSQL  │──CDC─>│ This Script  │──────>│ Celery Broker │
    │ (WAL        │       │ (Consumer)   │       │ (Redis/Rabbit)│
    └─────────────┘       └──────────────┘       └───────────────┘
                                                          │
                          ┌───────────────────────────────┤
                          │                               │
                    ┌─────▼─────┐                  ┌──────▼──────┐
                    │  Worker 1 │                  │  Worker 2   │
                    │ (process) │                  │  (process)  │
                    └───────────┘                  └─────────────┘

Usage:
    # Terminal 1: Start Redis
    docker run -p 6379:6379 redis:alpine

    # Terminal 2: Start Celery worker(s)
    celery -A celery_integration worker --loglevel=info

    # Terminal 3: Run CDC consumer
    python celery_integration.py
"""

import asyncio
import os
from typing import Any, Dict

import pgoutput_decoder
from celery import Celery
from pgoutput_decoder import ReplicationMessage, format_operation, get_table_name

# ============================================================================
# Celery Configuration
# ============================================================================

# Configure Celery broker (Redis in this example)
BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

app = Celery("cdc_tasks", broker=BROKER_URL, backend=RESULT_BACKEND)

# Celery configuration
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Retry configuration
    task_acks_late=True,  # Acknowledge after task completes (not before)
    task_reject_on_worker_lost=True,  # Requeue if worker dies
    worker_prefetch_multiplier=4,  # How many tasks to grab at once
)


# ============================================================================
# Celery Tasks
# ============================================================================


@app.task(bind=True, max_retries=3)
def process_cdc_message(self, message_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a CDC message in a Celery worker.

    This task runs in a separate worker process, allowing distributed
    processing across multiple machines.

    Args:
        message_data: CDC message as a dictionary with keys:
            - op: Operation type ("c", "u", "d", "r")
            - before: Row data before change (for UPDATE/DELETE)
            - after: Row data after change (for INSERT/UPDATE)
            - source: Metadata (table, schema, lsn, timestamp)
            - ts_ms: Timestamp in milliseconds

    Returns:
        dict: Result of processing (for debugging/monitoring)

    This task automatically retries up to 3 times on failure with
    exponential backoff.
    """
    try:
        operation = message_data["op"]
        source = message_data["source"]
        table = f"{source['schema']}.{source['table']}"

        print(f"[Worker {self.request.id[:8]}] Processing {operation} on {table}")

        # Route to specific handlers based on table
        if table == "public.orders":
            return handle_order_change(message_data)
        elif table == "public.customers":
            return handle_customer_change(message_data)
        elif table == "public.products":
            return handle_product_change(message_data)
        else:
            return handle_generic_change(message_data)

    except Exception as exc:
        # Retry with exponential backoff
        print(f"[Worker {self.request.id[:8]}] Error: {exc}, retrying...")
        raise self.retry(exc=exc, countdown=2**self.request.retries)


def handle_order_change(message_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle changes to the orders table.

    Business logic for order processing:
    - New orders: Send notification, update inventory
    - Updated orders: Handle status changes
    - Deleted orders: Clean up related data
    """
    operation = message_data["op"]

    if operation == "c":  # INSERT (Create)
        order = message_data["after"]
        print(f"  📦 New order {order.get('id')}: ${order.get('total', 0)}")

        # TODO: Your business logic here
        # - Update inventory
        # - Send order confirmation email
        # - Trigger fulfillment workflow
        # - Update analytics

        return {"status": "order_created", "order_id": order.get("id")}

    elif operation == "u":  # UPDATE
        old_order = message_data.get("before", {})
        new_order = message_data["after"]

        old_status = old_order.get("status")
        new_status = new_order.get("status")

        if old_status != new_status:
            print(f"  📝 Order {new_order.get('id')} status: {old_status} → {new_status}")

            # TODO: Handle status transitions
            # - "pending" → "paid": Process payment
            # - "paid" → "shipped": Send tracking notification
            # - "shipped" → "delivered": Customer satisfaction survey

        return {"status": "order_updated", "order_id": new_order.get("id")}

    elif operation == "d":  # DELETE
        order = message_data["before"]
        print(f"  🗑️  Order {order.get('id')} deleted")

        # TODO: Cleanup logic
        # - Cancel notifications
        # - Return inventory
        # - Archive order data

        return {"status": "order_deleted", "order_id": order.get("id")}

    return {"status": "unknown_operation"}


def handle_customer_change(message_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle changes to the customers table."""
    operation = message_data["op"]

    if operation == "c":  # New customer
        customer = message_data["after"]
        print(f"  👤 New customer {customer.get('id')}: {customer.get('email')}")

        # TODO: Welcome workflow
        # - Send welcome email
        # - Create user account
        # - Initialize preferences

        return {"status": "customer_created", "customer_id": customer.get("id")}

    elif operation == "u":  # Customer updated
        customer = message_data["after"]
        print(f"  📝 Customer {customer.get('id')} updated")

        # TODO: Handle updates
        # - Email changed: Send verification
        # - Address changed: Update shipping info

        return {"status": "customer_updated", "customer_id": customer.get("id")}

    return {"status": "processed"}


def handle_product_change(message_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle changes to the products table."""
    operation = message_data["op"]

    if operation == "c":  # New product
        product = message_data["after"]
        print(f"  🏷️  New product {product.get('id')}: {product.get('name')}")

        # TODO: Product onboarding
        # - Update search index
        # - Generate thumbnails
        # - Send to recommendation engine

    elif operation == "u":  # Product updated
        old_product = message_data.get("before", {})
        new_product = message_data["after"]

        old_price = old_product.get("price")
        new_price = new_product.get("price")

        if old_price != new_price:
            print(f"  💰 Price changed: ${old_price} → ${new_price}")

            # TODO: Handle price changes
            # - Update search index
            # - Notify price watchers
            # - Invalidate caches

    return {"status": "product_processed"}


def handle_generic_change(message_data: Dict[str, Any]) -> Dict[str, Any]:
    """Generic handler for other tables."""
    operation = message_data["op"]
    table = message_data["source"]["table"]
    print(f"  📄 {operation} on {table}")
    return {"status": "processed", "table": table}


# ============================================================================
# CDC Consumer (runs separately from Celery workers)
# ============================================================================


def message_to_dict(message: ReplicationMessage) -> Dict[str, Any]:
    """
    Convert ReplicationMessage to a JSON-serializable dict.

    Celery requires JSON-serializable data, so we convert the message
    to a plain dictionary.
    """
    return {
        "op": message.op,
        "before": message.before,
        "after": message.after,
        "source": dict(message.source),  # Convert PyDict to dict
        "ts_ms": message.ts_ms,
        "ts_us": message.ts_us,
        "ts_ns": message.ts_ns,
    }


async def consume_and_dispatch():
    """
    Main CDC consumer that dispatches messages to Celery.

    This function:
    1. Connects to PostgreSQL replication stream
    2. Receives CDC messages
    3. Dispatches each message as a Celery task
    4. Continues processing (doesn't wait for task completion)

    The Celery workers process tasks asynchronously.
    """
    print("Starting CDC consumer...")
    print(f"Celery broker: {BROKER_URL}")
    print("Dispatching messages to Celery workers...\n")

    reader = pgoutput_decoder.LogicalReplicationReader(
        publication_name="ecommerce_pub",
        slot_name="celery_consumer_slot",
        host="localhost",
        database="ecommerce_db",
        port=5432,
        user="postgres",
        password="password",
    )

    message_count = 0

    try:
        async for message in reader:
            if message is not None:
                message_count += 1

                # Convert to dict for Celery
                message_dict = message_to_dict(message)

                # Dispatch to Celery (asynchronous - doesn't wait)
                task = process_cdc_message.delay(message_dict)

                operation = format_operation(message.op)
                table = get_table_name(message)

                print(f"[{message_count}] Dispatched: {operation} on {table}")
                print(f"    Task ID: {task.id}")
                print(f"    Queue depth: ~{message_count} messages dispatched\n")

    except KeyboardInterrupt:
        print("\n\nStopping consumer...")
    finally:
        await reader.stop()
        print(f"\n✓ Consumer stopped. Dispatched {message_count} messages total.")


# ============================================================================
# Celery Tasks for Monitoring
# ============================================================================


@app.task
def health_check() -> Dict[str, str]:
    """
    Simple health check task for monitoring.

    Usage:
        from celery_integration import health_check
        result = health_check.delay()
        print(result.get(timeout=5))  # Returns: {"status": "healthy"}
    """
    return {"status": "healthy", "message": "Celery worker is running"}


# ============================================================================
# Main Execution
# ============================================================================


def main():
    """
    Main entry point for the CDC consumer.

    Run this to start consuming CDC messages and dispatching to Celery.
    Make sure Celery workers are running first!
    """
    print("=" * 70)
    print("Celery CDC Integration Example")
    print("=" * 70)
    print()
    print("This script consumes CDC messages and dispatches them to Celery workers.")
    print()
    print("Before running this, make sure:")
    print("  1. Redis is running: docker run -p 6379:6379 redis:alpine")
    print("  2. Celery workers are started: celery -A celery_integration worker")
    print("  3. PostgreSQL has CDC enabled and the publication exists")
    print()
    print("=" * 70)
    print()

    # Run the async consumer
    asyncio.run(consume_and_dispatch())


if __name__ == "__main__":
    main()


# ============================================================================
# Example: Monitoring Task Status
# ============================================================================
"""
You can monitor task status programmatically:

from celery_integration import app

# Get task result
task_id = "abc123..."
result = app.AsyncResult(task_id)

print(f"State: {result.state}")
print(f"Result: {result.result}")

# Check if task succeeded
if result.successful():
    print("Task completed!")
elif result.failed():
    print(f"Task failed: {result.info}")
elif result.state == "PENDING":
    print("Task not found or still in queue")

# Wait for result (blocking)
try:
    result_data = result.get(timeout=10)
    print(f"Task returned: {result_data}")
except Exception as e:
    print(f"Task error: {e}")
"""
