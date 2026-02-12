"""
Background Thread CDC Consumer for Synchronous Applications

This example shows how to integrate CDC streaming into synchronous applications
(Flask, Django, traditional Python apps) using a background thread. This is ideal for:

- Web applications (Flask, Django)
- Long-running services that need to do other work
- Applications with existing synchronous codebases
- Microservices that need CDC as a side-channel

The BackgroundCDCReader runs the async CDC consumer in a separate thread and
provides a thread-safe queue for retrieving messages from your sync code.

Prerequisites:
    - PostgreSQL 12+ with wal_level=logical
    - A publication: CREATE PUBLICATION my_pub FOR ALL TABLES;
    - A replication slot (created automatically on first connection)

Usage:
    python background_thread.py
"""

import asyncio
import threading
import time
from queue import Empty, Queue
from typing import Optional

import pgoutput_decoder
from pgoutput_decoder import ReplicationMessage, format_operation, get_table_name


class BackgroundCDCReader:
    """
    CDC reader that runs in a background thread.

    This class manages an async CDC reader in a separate thread, exposing
    a simple synchronous API for message retrieval. Messages are buffered
    in a thread-safe queue.

    Example:
        # Start the reader
        reader = BackgroundCDCReader(
            publication_name="my_pub",
            slot_name="my_slot",
            host="localhost",
            database="mydb",
            user="postgres",
            password="secret",
        )
        reader.start()

        # In your synchronous code
        while True:
            message = reader.get_message(timeout=1.0)
            if message:
                process_message(message)

        # Clean shutdown
        reader.stop()

    Thread Safety:
        This class is thread-safe. You can call get_message() from multiple
        threads, though typically you'll only call it from your main thread.
    """

    def __init__(
        self,
        publication_name: str,
        slot_name: str,
        host: str,
        database: str,
        port: int = 5432,
        user: str = "postgres",
        password: str = "",
        queue_size: int = 100,
    ):
        """
        Initialize the background CDC reader.

        Args:
            publication_name: PostgreSQL publication name
            slot_name: Replication slot name (unique per consumer)
            host: PostgreSQL host
            database: Database name
            port: PostgreSQL port (default: 5432)
            user: Database username
            password: Database password
            queue_size: Maximum messages to buffer (default: 100).
                       When full, the reader will block until messages are consumed.
                       This provides natural backpressure.
        """
        self._reader_kwargs = {
            "publication_name": publication_name,
            "slot_name": slot_name,
            "host": host,
            "database": database,
            "port": port,
            "user": user,
            "password": password,
        }
        self._queue: Queue[Optional[ReplicationMessage]] = Queue(maxsize=queue_size)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._started = False

    def start(self) -> None:
        """
        Start the background CDC reader thread.

        This spawns a new daemon thread that runs the async event loop.
        The thread will automatically stop when your program exits.

        Raises:
            RuntimeError: If the reader is already started
        """
        if self._started:
            raise RuntimeError("Reader already started")

        self._stop_event.clear()
        self._started = True

        # Create daemon thread so it dies when main program exits
        self._thread = threading.Thread(
            target=self._run_async_loop, name="CDC-Reader-Thread", daemon=True
        )
        self._thread.start()

        print(f"✓ CDC reader started in background (thread: {self._thread.name})")

    def stop(self, timeout: float = 5.0) -> None:
        """
        Stop the background reader thread gracefully.

        This signals the thread to stop and waits for it to finish.

        Args:
            timeout: Seconds to wait for thread to stop (default: 5.0)
                    If the thread doesn't stop in time, it will be left as a
                    daemon and killed when the program exits.
        """
        if not self._started:
            return

        print("Stopping CDC reader...")
        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                print(f"⚠ Warning: Thread didn't stop in {timeout}s (will exit as daemon)")
            else:
                print("✓ CDC reader stopped cleanly")

        self._thread = None
        self._started = False

    def get_message(self, timeout: Optional[float] = None) -> Optional[ReplicationMessage]:
        """
        Get the next CDC message from the queue.

        This blocks until a message is available or the timeout expires.

        Args:
            timeout: Seconds to wait for a message. None = wait forever
                    0 = return immediately if no message available

        Returns:
            ReplicationMessage if available, None if timeout or queue is empty

        Example:
            # Non-blocking check
            message = reader.get_message(timeout=0)
            if message:
                process(message)

            # Wait up to 1 second
            message = reader.get_message(timeout=1.0)

            # Block forever until message arrives
            message = reader.get_message()
        """
        try:
            return self._queue.get(timeout=timeout)
        except Empty:
            return None

    def queue_size(self) -> int:
        """
        Get the current number of messages waiting in the queue.

        Returns:
            Number of messages currently buffered
        """
        return self._queue.qsize()

    def is_alive(self) -> bool:
        """
        Check if the background thread is running.

        Returns:
            True if thread is alive, False otherwise
        """
        return self._thread is not None and self._thread.is_alive()

    def _run_async_loop(self) -> None:
        """
        Run the async event loop in the background thread.

        This is the thread's main function. It creates a new event loop
        and runs the async CDC consumer.
        """
        try:
            asyncio.run(self._consume_messages())
        except Exception as e:
            print(f"❌ CDC reader thread crashed: {e}")
            raise

    async def _consume_messages(self) -> None:
        """
        Async function that consumes CDC messages and puts them in the queue.

        This runs in the background thread's event loop.
        """
        reader = pgoutput_decoder.LogicalReplicationReader(**self._reader_kwargs)

        try:
            async for message in reader:
                # Check if we should stop
                if self._stop_event.is_set():
                    break

                if message is not None:
                    # Put message in queue (blocks if queue is full - backpressure!)
                    self._queue.put(message)

        except Exception as e:
            print(f"❌ Error in CDC consumer: {e}")
            raise
        finally:
            await reader.stop()


# ============================================================================
# Example Usage Patterns
# ============================================================================


def example_simple_loop():
    """
    Example 1: Simple polling loop

    This shows the basic pattern: start the reader, poll for messages,
    process them, then stop cleanly.
    """
    print("Example 1: Simple Polling Loop")
    print("=" * 60)

    # Start the background reader
    reader = BackgroundCDCReader(
        publication_name="ecommerce_pub",
        slot_name="background_example_slot",
        host="localhost",
        database="ecommerce_db",
        user="postgres",
        password="password",
        queue_size=50,  # Buffer up to 50 messages
    )

    reader.start()

    # Give it a moment to connect
    time.sleep(1)

    try:
        message_count = 0
        max_messages = 5

        print(f"\nProcessing up to {max_messages} messages...")
        print("(Waiting for changes to the database...)\n")

        while message_count < max_messages:
            # Poll for messages with 1 second timeout
            message = reader.get_message(timeout=1.0)

            if message:
                # Process the message
                operation = format_operation(message.op)
                table = get_table_name(message)
                print(f"{message_count + 1}. {operation} on {table}")
                print(f"   Queue depth: {reader.queue_size()}")
                message_count += 1
            else:
                # No message yet, show we're still waiting
                print(".", end="", flush=True)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    finally:
        # Always clean up
        reader.stop()
        print(f"\nProcessed {message_count} messages total.")


def example_flask_integration():
    """
    Example 2: Flask-style integration

    This shows how you might integrate the CDC reader into a Flask application.
    The reader runs continuously in the background while Flask handles HTTP requests.
    """
    print("\nExample 2: Flask-Style Integration")
    print("=" * 60)

    # Global reader instance (in Flask, this would be app.cdc_reader)
    cdc_reader = None

    def start_flask_app():
        """Simulate Flask app startup."""
        global cdc_reader

        print("Starting Flask app...")

        # Start CDC reader when app starts
        cdc_reader = BackgroundCDCReader(
            publication_name="ecommerce_pub",
            slot_name="flask_example_slot",
            host="localhost",
            database="ecommerce_db",
            user="postgres",
            password="password",
        )
        cdc_reader.start()

        print("✓ Flask app started with CDC reader\n")

    def simulate_http_request():
        """Simulate handling an HTTP request."""
        # In a real Flask app, this would be a route handler

        # Check for pending CDC messages
        message = cdc_reader.get_message(timeout=0)  # Non-blocking

        if message:
            table = get_table_name(message)
            return f"New change detected on {table}!"
        else:
            return "No changes pending"

    def shutdown_flask_app():
        """Simulate Flask app shutdown."""
        global cdc_reader
        print("\nShutting down Flask app...")
        if cdc_reader:
            cdc_reader.stop()
        print("✓ Flask app stopped\n")

    # Simulate Flask lifecycle
    try:
        start_flask_app()

        # Simulate some HTTP requests
        for i in range(5):
            time.sleep(1)
            response = simulate_http_request()
            print(f"Request {i + 1}: {response}")

    finally:
        shutdown_flask_app()


def example_message_processor():
    """
    Example 3: Dedicated message processor thread

    This shows a more sophisticated pattern where a separate thread
    continuously processes messages from the CDC reader.
    """
    print("\nExample 3: Dedicated Message Processor")
    print("=" * 60)

    processing = True

    def message_processor_thread(reader: BackgroundCDCReader):
        """
        Separate thread that processes messages continuously.

        In a real application, this might update caches, send notifications,
        trigger workflows, etc.
        """
        print("Message processor thread started\n")

        while processing:
            message = reader.get_message(timeout=1.0)

            if message:
                table = get_table_name(message)
                operation = format_operation(message.op)

                # Simulate business logic
                if table == "public.orders" and operation == "INSERT":
                    print(f"📦 Processing new order: {message.after}")
                    # TODO: Update inventory, send notification, etc.

                elif table == "public.customers" and operation == "INSERT":
                    print(f"👤 Processing new customer: {message.after}")
                    # TODO: Send welcome email, create account, etc.

                else:
                    print(f"📝 {operation} on {table}")

        print("Message processor thread stopped")

    # Start CDC reader
    cdc_reader = BackgroundCDCReader(
        publication_name="ecommerce_pub",
        slot_name="processor_example_slot",
        host="localhost",
        database="ecommerce_db",
        user="postgres",
        password="password",
    )
    cdc_reader.start()

    # Start processor thread
    processor = threading.Thread(target=message_processor_thread, args=(cdc_reader,), daemon=True)
    processor.start()

    try:
        # Main thread can do other work
        print("Main thread doing other work...")
        time.sleep(10)  # Simulate work

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        processing = False
        cdc_reader.stop()
        processor.join(timeout=2)


if __name__ == "__main__":
    # Run the examples
    print("Background Thread CDC Consumer Examples")
    print("=" * 60)
    print()

    # Uncomment the example you want to run:

    example_simple_loop()  # Basic polling pattern
    # example_flask_integration()  # Web framework integration
    # example_message_processor()  # Dedicated processor thread

    print("\n" + "=" * 60)
    print("Examples completed!")
