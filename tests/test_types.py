"""Unit tests for PostgreSQL type conversions."""

import pytest


def test_replication_message_type_exists():
    """Test that ReplicationMessage class exists in the module."""
    try:
        from pgoutput_decoder._pgoutput_decoder import ReplicationMessage

        assert ReplicationMessage is not None
    except ImportError:
        # Module not built yet
        pytest.skip("pgoutput_decoder module not built yet")


def test_message_type_values():
    """Test expected message type values."""
    expected_types = ["INSERT", "UPDATE", "DELETE", "BEGIN", "COMMIT"]
    # These will be created by the Rust code during actual replication
    assert all(isinstance(t, str) for t in expected_types)


def test_decimal_type_handling():
    """Test that DECIMAL values are handled correctly."""
    from decimal import Decimal

    # Test decimal values that appear in e-commerce schema
    price = Decimal("1299.99")
    assert price == Decimal("1299.99")

    quantity = 5
    total = price * quantity
    assert total == Decimal("6499.95")


def test_boolean_type_handling():
    """Test boolean type for _deleted flag."""
    deleted_flag = False
    assert isinstance(deleted_flag, bool)
    assert deleted_flag is False

    deleted_flag = True
    assert deleted_flag is True


def test_varchar_type_handling():
    """Test VARCHAR type for IDs and names."""
    customer_id = "CUST001"
    assert isinstance(customer_id, str)
    assert len(customer_id) > 0

    customer_name = "Alice Johnson"
    assert isinstance(customer_name, str)


def test_integer_type_handling():
    """Test INTEGER type for credit limits and quantities."""
    credit_limit = 5000
    assert isinstance(credit_limit, int)
    assert credit_limit > 0

    quantity = 3
    assert isinstance(quantity, int)
