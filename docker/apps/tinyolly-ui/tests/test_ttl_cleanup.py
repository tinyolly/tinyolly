"""
Tests for TTL-based data cleanup.

These tests verify:
- Automatic expiration of old data
- Retention policy enforcement
- Cleanup doesn't affect recent data
"""
import pytest


class TestTTLCleanup:
    """Tests for TTL-based data cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_expired_traces(self, storage):
        """Test cleaning up traces older than TTL."""
        pytest.skip("SQLite storage not yet implemented")

    @pytest.mark.asyncio
    async def test_cleanup_expired_logs(self, storage):
        """Test cleaning up logs older than TTL."""
        pytest.skip("SQLite storage not yet implemented")

    @pytest.mark.asyncio
    async def test_cleanup_expired_metrics(self, storage):
        """Test cleaning up metrics older than TTL."""
        pytest.skip("SQLite storage not yet implemented")

    @pytest.mark.asyncio
    async def test_cleanup_preserves_recent_data(self, storage):
        """Test that cleanup doesn't affect recent data."""
        pytest.skip("SQLite storage not yet implemented")

    @pytest.mark.asyncio
    async def test_cleanup_cascade_spans(self, storage):
        """Test that cleaning traces also cleans associated spans."""
        pytest.skip("SQLite storage not yet implemented")


class TestRetentionPolicy:
    """Tests for retention policy configuration."""

    @pytest.mark.asyncio
    async def test_custom_retention_period(self, storage):
        """Test setting custom retention period."""
        pytest.skip("SQLite storage not yet implemented")

    @pytest.mark.asyncio
    async def test_different_retention_per_type(self, storage):
        """Test different retention for traces vs metrics vs logs."""
        pytest.skip("SQLite storage not yet implemented")

    @pytest.mark.asyncio
    async def test_disable_cleanup(self, storage):
        """Test disabling automatic cleanup."""
        pytest.skip("SQLite storage not yet implemented")
