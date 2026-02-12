"""Custom exceptions for pgoutput-decoder."""


class ReplicationError(Exception):
    """Base exception for replication errors."""
    pass


class ConnectionError(ReplicationError):
    """Raised when connection to PostgreSQL fails."""
    pass


class SlotNotFoundError(ReplicationError):
    """Raised when the specified replication slot doesn't exist."""
    pass


class DecodingError(ReplicationError):
    """Raised when pgoutput message decoding fails."""
    pass
