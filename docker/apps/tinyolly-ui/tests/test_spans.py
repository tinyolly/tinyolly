"""
Tests for span storage and retrieval.

These tests verify:
- Span ingestion (single and batch)
- Span retrieval by trace ID
- Span events and links
- Span kinds and status codes
- Parent-child relationships
"""
import pytest


class TestSpanStorage:
    """Tests for span storage operations."""

    @pytest.mark.asyncio
    async def test_store_span(self, storage, sample_span):
        """Test storing a single span."""
        pytest.skip("SQLite storage not yet implemented")

    @pytest.mark.asyncio
    async def test_store_batch_spans(self, storage):
        """Test storing multiple spans in a batch."""
        pytest.skip("SQLite storage not yet implemented")

    @pytest.mark.asyncio
    async def test_get_spans_by_trace_id(self, storage):
        """Test retrieving all spans for a trace."""
        pytest.skip("SQLite storage not yet implemented")


class TestSpanAttributes:
    """Tests for span attributes and metadata."""

    @pytest.mark.asyncio
    async def test_span_with_events(self, storage):
        """Test span with multiple events."""
        pytest.skip("SQLite storage not yet implemented")

    @pytest.mark.asyncio
    async def test_span_with_links(self, storage):
        """Test span with links to other traces."""
        pytest.skip("SQLite storage not yet implemented")

    @pytest.mark.asyncio
    async def test_span_kinds(self, storage):
        """Test all span kinds (INTERNAL, SERVER, CLIENT, PRODUCER, CONSUMER)."""
        pytest.skip("SQLite storage not yet implemented")

    @pytest.mark.asyncio
    async def test_span_status_codes(self, storage):
        """Test all status codes (UNSET, OK, ERROR)."""
        pytest.skip("SQLite storage not yet implemented")


class TestSpanHierarchy:
    """Tests for span parent-child relationships."""

    @pytest.mark.asyncio
    async def test_parent_child_relationship(self, storage):
        """Test span with parent span ID."""
        pytest.skip("SQLite storage not yet implemented")

    @pytest.mark.asyncio
    async def test_root_span(self, storage):
        """Test root span (no parent)."""
        pytest.skip("SQLite storage not yet implemented")

    @pytest.mark.asyncio
    async def test_deep_span_tree(self, storage):
        """Test deeply nested span hierarchy."""
        pytest.skip("SQLite storage not yet implemented")


class TestSpanEdgeCases:
    """Tests for span edge cases."""

    @pytest.mark.asyncio
    async def test_span_with_large_attributes(self, storage):
        """Test span with many attributes."""
        pytest.skip("SQLite storage not yet implemented")

    @pytest.mark.asyncio
    async def test_span_with_binary_attributes(self, storage):
        """Test span with binary attribute values."""
        pytest.skip("SQLite storage not yet implemented")

    @pytest.mark.asyncio
    async def test_span_zero_duration(self, storage):
        """Test span with zero duration."""
        pytest.skip("SQLite storage not yet implemented")
