
Implement a PostgreSQL logical replication library that implements the following API:

cdc_reader = pgoutput_decoder.LogicalReplicationReader(
publication_name="test_pub",
slot_name="test_slot",
host=HOST,
database=DATABASE_NAME,
port=PORT,
user=USER,
password=PASSWORD,
)
for message in cdc_reader:
print(message.json(indent=2))

cdc_reader.stop()

The messages should be Debezium-compatible data structures. The client should also be able to acknowledge the messages and that way advance the LSN in the replication slot.

Implement the backend in Rust using pgwire-replication. Python bindings should be created using pyo3 and maturin. Use PostgreSQL's pgoutput plugin to decode replication events. Implement it using asyncio.