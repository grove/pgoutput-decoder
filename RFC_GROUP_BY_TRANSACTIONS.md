# RFC: Transaction Grouping API

- **Feature Name**: `transaction_grouping`
- **Start Date**: 2026-02-16
- **RFC PR**: N/A
- **Status**: Draft

## Summary

Add an API to group logical replication messages by their containing transactions, enabling users to process complete transactions atomically rather than individual messages.

## Motivation

Currently, `pgoutput-decoder` streams individual change messages without exposing transaction boundaries. Users receive:

```python
async for message in reader:
    # message is a single ReplicationMessage (INSERT, UPDATE, or DELETE)
    process(message)
```

While PostgreSQL's logical replication protocol includes transaction boundaries (`Begin` and `Commit` messages), these aren't currently exposed to users. This creates challenges for:

### Use Cases Requiring Transaction Grouping

1. **Atomic Processing**: Users need to process all changes in a transaction together
   ```python
   # Current: No guarantee these are from the same transaction
   async for msg in reader:
       if msg.op == "c":  # Could be from different transactions
           process_insert(msg)
   ```

2. **Transaction-Level Acknowledgment**: Acknowledge only after processing entire transaction
   ```python
   # Current: Must acknowledge after each message or risk duplicate processing
   async for msg in reader:
       await process(msg)
       await reader.acknowledge(msg.source['lsn'])  # Can't wait for transaction end
   ```

3. **Bulk Operations**: Batch database writes by transaction for better performance
   ```python
   # Desired: Bulk insert all changes from a transaction
   async for txn in reader.transactions():
       bulk_insert(txn.messages)  # Much faster than individual inserts
   ```

4. **Debugging and Auditing**: Replay or analyze complete transactions
   ```python
   # Desired: Find transactions that touched multiple tables
   async for txn in reader.transactions():
       affected_tables = {get_table_name(msg) for msg in txn.messages}
       if len(affected_tables) > 5:
           log_warning(f"Large transaction {txn.xid} affected {affected_tables}")
   ```

## Guide-level Explanation

### For Users

After this RFC is implemented, users will have two ways to consume replication messages:

#### Option 1: Individual Messages (Current Behavior)

```python
from pgoutput_decoder import LogicalReplicationReader

reader = LogicalReplicationReader(
    publication_name="ecommerce_pub",
    slot_name="ecommerce_slot",
    host="localhost",
    database="ecommerce_db",
)

# Process one message at a time (existing API)
async for message in reader:
    print(f"Change: {message.op} on {message.source['table']}")
    await process_message(message)
```

#### Option 2: Grouped by Transaction (New API)

```python
from pgoutput_decoder import LogicalReplicationReader

reader = LogicalReplicationReader(
    publication_name="ecommerce_pub",
    slot_name="ecommerce_slot",
    host="localhost",
    database="ecommerce_db",
)

# Process complete transactions (new API)
async for transaction in reader.transactions():
    print(f"Transaction {transaction.xid} with {len(transaction)} messages")
    
    # All messages are guaranteed to be from the same transaction
    for message in transaction.messages:
        print(f"  - {message.op} on {message.source['table']}")
    
    # Bulk process the entire transaction
    await bulk_insert_to_warehouse(transaction.messages)
    
    # Acknowledge once per transaction
    await reader.acknowledge(transaction.commit_lsn)
```

### Transaction Object

The new `Transaction` class provides:

```python
@dataclass
class Transaction:
    """A complete logical replication transaction."""
    
    xid: int                              # PostgreSQL transaction ID
    commit_lsn: str                       # LSN where transaction committed
    commit_ts: int                        # Commit timestamp (ms since epoch)
    messages: List[ReplicationMessage]    # All changes in transaction
    
    def __len__(self) -> int:
        """Number of messages in transaction."""
        return len(self.messages)
    
    def __iter__(self):
        """Iterate over messages."""
        return iter(self.messages)
```

### Example: Filtering Large Transactions

```python
async def process_large_transactions():
    reader = LogicalReplicationReader(...)
    
    async for txn in reader.transactions():
        # Skip small transactions
        if len(txn.messages) < 10:
            await reader.acknowledge(txn.commit_lsn)
            continue
        
        # Process only large transactions
        print(f"Processing large transaction: {len(txn)} messages")
        for msg in txn:
            await process_message(msg)
        
        await reader.acknowledge(txn.commit_lsn)
```

### Example: Cross-Table Consistency

```python
async def maintain_denormalized_views():
    """Update materialized views when transactions touch multiple tables."""
    reader = LogicalReplicationReader(...)
    
    async for txn in reader.transactions():
        affected_tables = {msg.source['table'] for msg in txn.messages}
        
        # Rebuild denormalized views if transaction spans tables
        if 'orders' in affected_tables and 'order_lines' in affected_tables:
            await rebuild_order_summary_view(txn.messages)
        
        await reader.acknowledge(txn.commit_lsn)
```

## Reference-level Explanation

### Python API

#### New Class: `Transaction`

```python
from dataclasses import dataclass
from typing import List

@dataclass
class Transaction:
    """
    A complete PostgreSQL logical replication transaction.
    
    Attributes:
        xid: Transaction ID assigned by PostgreSQL
        commit_lsn: Log Sequence Number where transaction committed
        commit_ts: Commit timestamp in milliseconds since Unix epoch
        messages: List of all replication messages in this transaction
    
    Examples:
        >>> async for txn in reader.transactions():
        ...     print(f"Transaction {txn.xid} has {len(txn)} messages")
        ...     for msg in txn:
        ...         process(msg)
    """
    xid: int
    commit_lsn: str
    commit_ts: int
    messages: List[ReplicationMessage]
    
    def __len__(self) -> int:
        """Return the number of messages in the transaction."""
        return len(self.messages)
    
    def __iter__(self):
        """Iterate over messages in the transaction."""
        return iter(self.messages)
    
    def __repr__(self) -> str:
        return f"Transaction(xid={self.xid}, messages={len(self.messages)})"
```

#### New Method: `LogicalReplicationReader.transactions()`

```python
class LogicalReplicationReader:
    """PostgreSQL logical replication reader."""
    
    def __aiter__(self):
        """
        Iterate over individual messages (existing behavior).
        
        Yields:
            ReplicationMessage: Individual change messages
        """
        return self
    
    async def __anext__(self) -> ReplicationMessage:
        """Get next individual message."""
        ...
    
    async def transactions(self) -> AsyncIterator[Transaction]:
        """
        Iterate over complete transactions.
        
        This method buffers messages from the replication stream until
        a COMMIT message is received, then yields the complete transaction.
        
        Yields:
            Transaction: Complete transaction with all messages
        
        Raises:
            ReplicationError: If connection fails or protocol error occurs
            
        Examples:
            >>> reader = LogicalReplicationReader(...)
            >>> async for txn in reader.transactions():
            ...     print(f"Processing transaction {txn.xid}")
            ...     for msg in txn.messages:
            ...         await process(msg)
            ...     await reader.acknowledge(txn.commit_lsn)
        
        Note:
            - Transactions are buffered in memory until COMMIT
            - Large transactions may consume significant memory
            - Use max_transaction_size parameter to limit buffering
        """
        ...
```

### Rust Implementation

#### New Structures in `src/replication.rs`

```rust
use std::collections::VecDeque;

/// Buffer for accumulating messages within a transaction
pub struct TransactionBuffer {
    /// Current transaction being accumulated
    current_txn: Option<InProgressTransaction>,
    /// Queue of completed transactions ready to yield
    completed: VecDeque<Transaction>,
}

/// Transaction being accumulated (not yet committed)
struct InProgressTransaction {
    xid: u32,
    messages: Vec<ReplicationMessage>,
}

/// Complete transaction ready to yield to Python
#[pyclass]
pub struct Transaction {
    #[pyo3(get)]
    xid: u32,
    #[pyo3(get)]
    commit_lsn: String,
    #[pyo3(get)]
    commit_ts: i64,
    #[pyo3(get)]
    messages: Vec<ReplicationMessage>,
}

impl LogicalReplicationReader {
    /// Read and buffer messages until a complete transaction is available
    async fn read_transaction(&mut self) -> PyResult<Option<Transaction>> {
        let mut messages = Vec::new();
        let mut xid: Option<u32> = None;
        let mut commit_lsn: Option<String> = None;
        let mut commit_ts: Option<i64> = None;

        loop {
            // Read next message from stream
            let event = self.client.read_message().await
                .map_err(to_py_err)?;
            
            match event {
                ReplicationEvent::PgOutput(pgoutput_msg) => {
                    match pgoutput_msg {
                        PgOutputMessage::Begin(begin) => {
                            xid = Some(begin.xid);
                        }
                        PgOutputMessage::Commit(commit) => {
                            commit_lsn = Some(commit.lsn.to_string());
                            commit_ts = Some(commit.timestamp as i64);
                            break; // Transaction complete
                        }
                        PgOutputMessage::Insert(insert) => {
                            let msg = self.decoder.decode_insert(insert)?;
                            messages.push(msg);
                        }
                        PgOutputMessage::Update(update) => {
                            let msg = self.decoder.decode_update(update)?;
                            messages.push(msg);
                        }
                        PgOutputMessage::Delete(delete) => {
                            let msg = self.decoder.decode_delete(delete)?;
                            messages.push(msg);
                        }
                        _ => {} // Ignore relation, type, truncate, etc.
                    }
                }
                ReplicationEvent::Keepalive(_) => {
                    // Continue waiting for transaction
                    continue;
                }
                _ => {}
            }
        }

        Ok(Some(Transaction {
            xid: xid.ok_or_else(|| PyRuntimeError::new_err("Transaction missing XID"))?,
            commit_lsn: commit_lsn.ok_or_else(|| PyRuntimeError::new_err("Transaction missing commit LSN"))?,
            commit_ts: commit_ts.ok_or_else(|| PyRuntimeError::new_err("Transaction missing commit timestamp"))?,
            messages,
        }))
    }
}

#[pymethods]
impl LogicalReplicationReader {
    /// Create async iterator over transactions
    fn transactions<'py>(&'py mut self, py: Python<'py>) -> PyResult<&'py PyAny> {
        pyo3_asyncio::tokio::future_into_py(py, async move {
            // This will be called repeatedly by Python's async iterator protocol
            self.read_transaction().await
        })
    }
}

#[pymethods]
impl Transaction {
    fn __len__(&self) -> usize {
        self.messages.len()
    }
    
    fn __iter__(&self) -> TransactionIterator {
        TransactionIterator {
            messages: self.messages.clone(),
            index: 0,
        }
    }
    
    fn __repr__(&self) -> String {
        format!("Transaction(xid={}, messages={})", self.xid, self.messages.len())
    }
}

#[pyclass]
struct TransactionIterator {
    messages: Vec<ReplicationMessage>,
    index: usize,
}

#[pymethods]
impl TransactionIterator {
    fn __iter__(slf: PyRef<Self>) -> PyRef<Self> {
        slf
    }
    
    fn __next__(mut slf: PyRefMut<Self>) -> Option<ReplicationMessage> {
        if slf.index < slf.messages.len() {
            let msg = slf.messages[slf.index].clone();
            slf.index += 1;
            Some(msg)
        } else {
            None
        }
    }
}
```

#### Changes to `src/lib.rs`

```rust
#[pymodule]
fn _pgoutput_decoder(py: Python, m: &PyModule) -> PyResult<()> {
    // Register classes
    m.add_class::<LogicalReplicationReader>()?;
    m.add_class::<ReplicationMessage>()?;
    m.add_class::<Transaction>()?;  // NEW

    // Register functions
    m.add_function(wrap_pyfunction!(message_to_debezium_json, m)?)?;

    // Register exceptions
    m.add("ReplicationError", py.get_type::<PyRuntimeError>())?;

    Ok(())
}
```

### Configuration Options

Add optional parameters to control transaction buffering:

```python
class LogicalReplicationReader:
    async def transactions(
        self,
        max_transaction_size: Optional[int] = None,
        timeout_ms: Optional[int] = None,
    ) -> AsyncIterator[Transaction]:
        """
        Args:
            max_transaction_size: Maximum number of messages per transaction.
                                 Raises error if exceeded (prevents OOM).
            timeout_ms: Maximum time to wait for transaction completion.
                       Returns partial transaction on timeout.
        """
```

## Drawbacks

### 1. Memory Consumption

Buffering entire transactions in memory can be problematic for large transactions:

```python
# A transaction with 1 million INSERTs will consume significant memory
async for txn in reader.transactions():
    # txn.messages contains all 1 million messages in RAM
    process(txn)
```

**Mitigation**: Add `max_transaction_size` parameter to fail early.

### 2. Increased Latency

Messages are held until transaction commits:

```python
# If a transaction runs for 30 minutes, no messages are yielded
# until the COMMIT arrives
async for txn in reader.transactions():
    # 30 minutes of latency before first message
    process(txn)
```

**Mitigation**: Document this clearly, recommend message-by-message for low-latency use cases.

### 3. API Complexity

Two ways to consume messages might confuse users:

```python
# Which should I use?
async for msg in reader:           # Option 1
    ...

async for txn in reader.transactions():  # Option 2
    ...
```

**Mitigation**: Clear documentation with decision tree.

### 4. Testing Burden

Need to test both code paths thoroughly, doubling test complexity.

**Mitigation**: Share common test fixtures, use parametrized tests.

## Rationale and Alternatives

### Why This Design?

**Option 1: `.transactions()` method (Chosen)**

✅ Explicit - clear intent  
✅ Backward compatible - doesn't break existing code  
✅ Pythonic - follows async iterator conventions  
✅ Flexible - users choose per use-case  

**Option 2: Constructor parameter `group_by_transaction=True`**

❌ Less discoverable  
❌ Either-or choice, not both  
❌ Changes return type based on parameter  

**Option 3: Separate class `TransactionReader`**

❌ Code duplication  
❌ Two classes to maintain  
❌ Harder to switch between modes  

### Alternative Approaches Not Chosen

#### 1. Always Group by Transaction (Breaking Change)

```python
# Always return transactions
async for txn in reader:
    for msg in txn.messages:
        process(msg)
```

**Rejected**: Breaking change, forces buffering on all users.

#### 2. Callback-Based API

```python
reader.on_transaction(callback)
reader.on_message(callback)
```

**Rejected**: Not Pythonic, harder to reason about control flow.

#### 3. Pull-Based API

```python
txn = await reader.next_transaction()
```

**Rejected**: Doesn't fit async iterator pattern, less ergonomic.

## Prior Art

### Debezium (Java)

Debezium exposes transaction metadata but doesn't group messages:

```java
// Debezium includes transaction.id in each message
for (SourceRecord record : records) {
    String txId = record.sourceOffset().get("transaction.id");
    // User must group manually
}
```

### pg_recvlogical (C)

PostgreSQL's native tool streams messages individually:

```bash
pg_recvlogical --start -f - | while read line; do
    # Process individual messages
done
```

### kafka-connect-jdbc

JDBC connector has similar pattern - buffers by transaction:

```java
transactions.forEach(txn -> {
    // Process all changes in transaction atomically
    processBatch(txn.records);
});
```

### python-pgreplicationclient

Another Python library that exposes raw messages:

```python
for msg in conn.messages():
    # Individual messages, no transaction grouping
    process(msg)
```

**Learning**: Most tools don't group by transaction. This is an opportunity to differentiate.

## Unresolved Questions

### 1. How to Handle Extremely Large Transactions?

**Question**: What happens if a transaction has 10 million rows?

**Options**:
- A) Fail with error (current plan)
- B) Stream partial transactions
- C) Skip and log warning
- D) Split into batches

**Recommendation**: Start with A, add B in future RFC.

### 2. Should We Expose Begin/Commit Messages?

**Question**: Should users see `Begin` and `Commit` as messages?

```python
# Option 1: Hidden (proposed)
async for txn in reader.transactions():
    # Only data changes (INSERT/UPDATE/DELETE)
    pass

# Option 2: Exposed
async for txn in reader.transactions():
    assert txn.messages[0].op == "b"  # BEGIN
    assert txn.messages[-1].op == "c"  # COMMIT
```

**Recommendation**: Hide for now, expose if requested.

### 3. Nested Transactions (Savepoints)?

**Question**: How to handle `SAVEPOINT` and `ROLLBACK TO`?

PostgreSQL's logical replication protocol doesn't include savepoint information.

**Recommendation**: Document as unsupported.

### 4. Should `.transactions()` Be Synchronous or Create New Iterator?

**Question**: Should we require creating a new reader?

```python
# Option 1: Chained (proposed)
reader = LogicalReplicationReader(...)
async for txn in reader.transactions():
    pass

# Option 2: Separate readers
msg_reader = LogicalReplicationReader(...)
txn_reader = TransactionGroupingReader(msg_reader)
```

**Recommendation**: Option 1 (chained) for simplicity.

## Future Possibilities

### 1. Streaming Large Transactions

For transactions too large to buffer:

```python
async for txn in reader.transactions(stream_large=True):
    async for msg in txn.stream():  # Lazy iteration
        process(msg)
```

### 2. Transaction Filtering

Filter transactions before buffering:

```python
async for txn in reader.transactions(
    min_size=10,  # Skip small transactions
    tables=['orders', 'customers'],  # Only these tables
):
    process(txn)
```

### 3. Transaction Metadata

Expose more PostgreSQL metadata:

```python
@dataclass
class Transaction:
    xid: int
    commit_lsn: str
    commit_ts: int
    messages: List[ReplicationMessage]
    
    # Future additions:
    user: str  # PostgreSQL user who ran transaction
    application_name: str  # From pg_stat_activity
    duration_ms: int  # How long transaction ran
```

### 4. Parallel Transaction Processing

Process non-conflicting transactions in parallel:

```python
async with reader.parallel_transactions(workers=4) as stream:
    async for txn in stream:
        # Non-overlapping transactions processed in parallel
        await process(txn)
```

### 5. Transaction Replay

Add ability to replay transactions from a position:

```python
# Replay last 100 transactions
async for txn in reader.replay(from_lsn=last_checkpoint, limit=100):
    redo(txn)
```

## Implementation Plan

### Phase 1: Core Implementation (v0.2.0)

**Week 1-2**: Rust implementation
- [ ] Add `Transaction` struct
- [ ] Implement transaction buffering in `LogicalReplicationReader`
- [ ] Add `.transactions()` method
- [ ] PyO3 bindings for `Transaction`

**Week 3**: Python API
- [ ] Python type stubs for `Transaction`
- [ ] Update `__init__.py` exports
- [ ] Add helper functions

**Week 4**: Testing
- [ ] Unit tests for transaction buffering (Rust)
- [ ] E2E tests with testcontainers (Python)
- [ ] Performance benchmarks
- [ ] Memory usage tests

### Phase 2: Documentation & Release (v0.2.0)

**Week 5**: Documentation
- [ ] Update README with examples
- [ ] Add docstrings
- [ ] Create migration guide
- [ ] Update API reference

**Week 6**: Release
- [ ] Update CHANGELOG
- [ ] Bump version to 0.2.0
- [ ] Release to PyPI
- [ ] Announce on GitHub

### Phase 3: Future Enhancements (v0.3.0+)

- [ ] Streaming large transactions
- [ ] Transaction filtering
- [ ] Enhanced metadata
- [ ] Performance optimizations

## Success Metrics

### User Adoption

- [ ] 25% of users adopt `.transactions()` within 3 months
- [ ] Positive feedback on GitHub Discussions
- [ ] At least 2 community-contributed examples

### Performance

- [ ] No more than 5% overhead vs. message-by-message
- [ ] Less than 10MB memory overhead for typical transactions

### Quality

- [ ] >80% test coverage for transaction code
- [ ] No P0/P1 bugs reported within first month
- [ ] Documentation rated 4+ stars

## Conclusion

Transaction grouping addresses a real user need for atomic processing of logical replication changes. The proposed API is:

- **Backward compatible**: Existing code continues to work
- **Explicit**: `.transactions()` makes intent clear
- **Flexible**: Users choose based on their use case
- **Well-documented**: Clear examples and guidelines

The implementation is straightforward, with most complexity in Rust buffering logic. The Python API is clean and Pythonic.

**Recommendation**: Proceed with implementation for v0.2.0 release.
