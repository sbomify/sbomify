"""Tests for custom domain validation."""

from sbomify.apps.teams.validators import validate_custom_domain


class TestCustomDomainValidator:
    """Test suite for custom domain validation."""

    def test_valid_domains(self) -> None:
        """Test that valid FQDNs are accepted."""
        valid_domains = [
            "app.example.com",
            "subdomain.example.com",
            "deep.subdomain.example.com",
            "my-app.example.com",
            "app123.example.com",
            "subdomain.example.co.uk",
            "api.company.io",
            "a.b.c.d.example.com",
            "my-cool-app.staging.example.com",
        ]

        for domain in valid_domains:
            is_valid, error = validate_custom_domain(domain)
            assert is_valid, f"Expected '{domain}' to be valid, got error: {error}"
            assert error is None, f"Valid domain should not have error message: {error}"

    def test_uppercase_normalized(self) -> None:
        """Test that uppercase domains are accepted and normalized."""
        is_valid, error = validate_custom_domain("APP.EXAMPLE.COM")
        assert is_valid, f"Uppercase domain should be valid, got error: {error}"
        assert error is None

    def test_empty_domain(self) -> None:
        """Test that empty domains are rejected."""
        test_cases = ["", "   ", "\t", "\n"]
        for domain in test_cases:
            is_valid, error = validate_custom_domain(domain)
            assert not is_valid, f"Empty domain '{repr(domain)}' should be invalid"
            assert "empty" in error.lower() or "whitespace" in error.lower()

    def test_protocol_rejected(self) -> None:
        """Test that domains with protocols are rejected."""
        invalid_domains = [
            "http://example.com",
            "https://app.example.com",
            "ftp://files.example.com",
            "ws://socket.example.com",
        ]

        for domain in invalid_domains:
            is_valid, error = validate_custom_domain(domain)
            assert not is_valid, f"Domain with protocol '{domain}' should be invalid"
            assert "protocol" in error.lower()

    def test_port_rejected(self) -> None:
        """Test that domains with ports are rejected."""
        invalid_domains = [
            "app.example.com:8080",
            "api.example.com:443",
            "localhost:3000",
            "example.com:80",
        ]

        for domain in invalid_domains:
            is_valid, error = validate_custom_domain(domain)
            assert not is_valid, f"Domain with port '{domain}' should be invalid"
            assert "port" in error.lower()

    def test_path_rejected(self) -> None:
        """Test that domains with paths are rejected."""
        invalid_domains = [
            "app.example.com/path",
            "api.example.com/v1/endpoint",
            "example.com/",
            "app.example.com?query=1",
            "app.example.com#anchor",
        ]

        for domain in invalid_domains:
            is_valid, error = validate_custom_domain(domain)
            assert not is_valid, f"Domain with path/query '{domain}' should be invalid"
            assert any(keyword in error.lower() for keyword in ["path", "query"]), (
                f"Error message should mention path/query: {error}"
            )

    def test_whitespace_rejected(self) -> None:
        """Test that domains with whitespace are rejected."""
        invalid_domains = [
            "app example.com",
            "app.example .com",
            "app.example. com",
            "app.example.com ",
            " app.example.com",
        ]

        for domain in invalid_domains:
            is_valid, error = validate_custom_domain(domain)
            assert not is_valid, f"Domain with whitespace '{domain}' should be invalid"
            assert "whitespace" in error.lower() or "leading" in error.lower() or "trailing" in error.lower()

    def test_wildcard_rejected(self) -> None:
        """Test that wildcard domains are rejected."""
        invalid_domains = [
            "*.example.com",
            "app.*.example.com",
            "app.example.*",
        ]

        for domain in invalid_domains:
            is_valid, error = validate_custom_domain(domain)
            assert not is_valid, f"Wildcard domain '{domain}' should be invalid"
            assert "wildcard" in error.lower()

    def test_ip_addresses_rejected(self) -> None:
        """Test that IP addresses are rejected."""
        invalid_domains = [
            "192.168.1.1",
            "10.0.0.1",
            "172.16.0.1",
            "8.8.8.8",
        ]

        for domain in invalid_domains:
            is_valid, error = validate_custom_domain(domain)
            assert not is_valid, f"IP address '{domain}' should be invalid"
            assert "ip" in error.lower() or "address" in error.lower()

    def test_single_label_rejected(self) -> None:
        """Test that single-label domains are rejected."""
        invalid_domains = [
            "localhost",
            "example",
            "myapp",
        ]

        for domain in invalid_domains:
            is_valid, error = validate_custom_domain(domain)
            assert not is_valid, f"Single-label domain '{domain}' should be invalid"
            assert "fully qualified" in error.lower() or "two parts" in error.lower()

    def test_too_long_rejected(self) -> None:
        """Test that domains exceeding 253 characters are rejected."""
        # Create a domain that's too long
        long_label = "a" * 63  # Max label length
        long_domain = ".".join([long_label] * 5)  # 5 * 63 + 4 dots = 319 chars

        is_valid, error = validate_custom_domain(long_domain)
        assert not is_valid, "Domain over 253 characters should be invalid"
        assert "too long" in error.lower()

    def test_label_too_long_rejected(self) -> None:
        """Test that labels exceeding 63 characters are rejected."""
        long_label = "a" * 64
        domain = f"{long_label}.example.com"

        is_valid, error = validate_custom_domain(domain)
        assert not is_valid, "Label over 63 characters should be invalid"
        assert "too long" in error.lower()

    def test_invalid_characters_rejected(self) -> None:
        """Test that domains with invalid characters are rejected."""
        invalid_domains = [
            "app_test.example.com",  # underscore
            "app@example.com",  # @ symbol
            "app!.example.com",  # exclamation
            "app$.example.com",  # dollar sign
            "app%20.example.com",  # URL encoding
            "app[].example.com",  # brackets
        ]

        for domain in invalid_domains:
            is_valid, error = validate_custom_domain(domain)
            assert not is_valid, f"Domain with invalid characters '{domain}' should be invalid"
            assert "invalid characters" in error.lower()

    def test_hyphen_placement_rejected(self) -> None:
        """Test that labels starting or ending with hyphens are rejected."""
        invalid_domains = [
            "-app.example.com",  # starts with hyphen
            "app-.example.com",  # ends with hyphen
            "-app-.example.com",  # both
            "app.-example.com",  # subdomain starts with hyphen
            "app.example-.com",  # subdomain ends with hyphen
        ]

        for domain in invalid_domains:
            is_valid, error = validate_custom_domain(domain)
            assert not is_valid, f"Domain with invalid hyphen placement '{domain}' should be invalid"
            assert "hyphen" in error.lower()

    def test_empty_labels_rejected(self) -> None:
        """Test that domains with empty labels (consecutive dots) are rejected."""
        invalid_domains = [
            "app..example.com",
            ".app.example.com",
            "app.example.com.",
            "app.example..com",
        ]

        for domain in invalid_domains:
            is_valid, error = validate_custom_domain(domain)
            assert not is_valid, f"Domain with empty label '{domain}' should be invalid"
            assert "empty" in error.lower() or "consecutive" in error.lower()

    def test_numeric_tld_rejected(self) -> None:
        """Test that domains with all-numeric TLD are rejected."""
        invalid_domains = [
            "app.example.123",
            "subdomain.test.999",
        ]

        for domain in invalid_domains:
            is_valid, error = validate_custom_domain(domain)
            assert not is_valid, f"Domain with numeric TLD '{domain}' should be invalid"
            assert "numeric" in error.lower()

    def test_edge_cases(self) -> None:
        """Test edge cases and boundary conditions."""
        # Valid: exactly 63 character label
        max_label = "a" * 63
        is_valid, error = validate_custom_domain(f"{max_label}.example.com")
        assert is_valid, f"63-character label should be valid, got error: {error}"

        # Valid: exactly 253 character domain
        # 253 chars = 61 + dot + 61 + dot + 61 + dot + 61 + dot + 5 = 253
        labels = ["a" * 61, "b" * 61, "c" * 61, "d" * 61, "e" * 5]
        domain_253 = ".".join(labels)
        assert len(domain_253) == 253, f"Expected 253 chars, got {len(domain_253)}"
        is_valid, error = validate_custom_domain(domain_253)
        assert is_valid, f"253-character domain should be valid, got error: {error}"

        # Valid: minimum valid domain (2 labels)
        is_valid, error = validate_custom_domain("a.b")
        assert is_valid, f"Two single-char labels should be valid, got error: {error}"

    def test_real_world_domains(self) -> None:
        """Test real-world domain patterns."""
        valid_domains = [
            "app.customer-name.io",
            "staging-api.company.com",
            "v2.api.service.cloud",
            "my-app-123.prod.example.org",
            "subdomain.example.co.uk",
            "app.example.com.au",
        ]

        for domain in valid_domains:
            is_valid, error = validate_custom_domain(domain)
            assert is_valid, f"Real-world domain '{domain}' should be valid, got error: {error}"
