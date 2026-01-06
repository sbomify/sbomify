"""Tests for plugin utility functions."""

import pytest

from sbomify.apps.plugins.utils import compute_config_hash, compute_content_digest


class TestComputeConfigHash:
    """Tests for compute_config_hash function."""

    def test_empty_config(self) -> None:
        """Test hash of empty configuration."""
        hash1 = compute_config_hash({})
        hash2 = compute_config_hash({})

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length

    def test_none_config(self) -> None:
        """Test that None config is treated as empty dict."""
        hash_none = compute_config_hash(None)
        hash_empty = compute_config_hash({})

        assert hash_none == hash_empty

    def test_deterministic(self) -> None:
        """Test that same config produces same hash."""
        config = {"key": "value", "number": 42}

        hash1 = compute_config_hash(config)
        hash2 = compute_config_hash(config)

        assert hash1 == hash2

    def test_key_order_independent(self) -> None:
        """Test that key order doesn't affect hash."""
        config1 = {"a": 1, "b": 2, "c": 3}
        config2 = {"c": 3, "a": 1, "b": 2}

        hash1 = compute_config_hash(config1)
        hash2 = compute_config_hash(config2)

        assert hash1 == hash2

    def test_different_configs_different_hashes(self) -> None:
        """Test that different configs produce different hashes."""
        config1 = {"key": "value1"}
        config2 = {"key": "value2"}

        hash1 = compute_config_hash(config1)
        hash2 = compute_config_hash(config2)

        assert hash1 != hash2


class TestComputeContentDigest:
    """Tests for compute_content_digest function."""

    def test_empty_content(self) -> None:
        """Test hash of empty bytes."""
        digest = compute_content_digest(b"")

        # SHA256 of empty string is well-known
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert digest == expected

    def test_deterministic(self) -> None:
        """Test that same content produces same digest."""
        content = b"Hello, World!"

        digest1 = compute_content_digest(content)
        digest2 = compute_content_digest(content)

        assert digest1 == digest2

    def test_different_content_different_digest(self) -> None:
        """Test that different content produces different digest."""
        content1 = b"Hello"
        content2 = b"World"

        digest1 = compute_content_digest(content1)
        digest2 = compute_content_digest(content2)

        assert digest1 != digest2

    def test_digest_length(self) -> None:
        """Test that digest is correct length."""
        digest = compute_content_digest(b"test content")

        assert len(digest) == 64  # SHA256 hex length

