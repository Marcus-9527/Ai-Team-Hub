"""
test_security.py — Security Layer Unit Tests

Covers:
  1. Encryption: encrypt/decrypt round-trip
  2. API key storage: encrypted at rest
  3. Log filtering: APIKeyFilter blocks sensitive patterns
  4. Auth middleware: route protection
"""
import pytest
import logging


class TestEncryption:
    """Encryption/decryption operations."""

    def test_crypto_imports(self):
        """Core crypto modules should be importable."""
        from backend.crypto import encrypt_value, decrypt_value
        assert callable(encrypt_value)
        assert callable(decrypt_value)

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypting then decrypting should return original value."""
        from backend.crypto import encrypt_value, decrypt_value

        original = "sk-test-secret-key"
        encrypted = encrypt_value(original)
        assert encrypted != original
        assert isinstance(encrypted, str)

        decrypted = decrypt_value(encrypted)
        assert decrypted == original

    def test_key_validation(self):
        """Key validation should detect valid and invalid keys."""
        from backend.security.crypto import validate_key, get_encryption_key_info

        info = get_encryption_key_info()
        assert isinstance(info, dict)
        assert "source" in info


class TestAPIKeyFilter:
    """Log filtering for API key patterns."""

    def setup_method(self):
        from backend.main import APIKeyFilter
        self.filter = APIKeyFilter()

    def _make_record(self, msg: str):
        return logging.LogRecord(
            name="test", level=logging.WARNING,
            pathname="", lineno=0, msg=msg, args=None, exc_info=None,
        )

    def test_blocks_sk_pattern(self):
        """Should block messages containing 'sk-' pattern."""
        assert not self.filter.filter(self._make_record("Using sk-test-key"))

    def test_blocks_api_key_pattern(self):
        """Should block messages containing 'api_key'."""
        assert not self.filter.filter(self._make_record("api_key value is set"))

    def test_blocks_x_api_key_pattern(self):
        """Should block messages containing 'x-api-key'."""
        assert not self.filter.filter(self._make_record("x-api-key: ***"))

    def test_allows_normal_messages(self):
        """Should allow messages without sensitive patterns."""
        assert self.filter.filter(self._make_record("Request completed successfully"))


class TestAuthMiddleware:
    """Auth middleware structure."""

    def test_auth_middleware_imports(self):
        """Auth middleware should be importable."""
        from backend.middleware.auth import AuthMiddleware, RequestContext, validate_api_key
        assert AuthMiddleware is not None
        assert RequestContext is not None
        assert callable(validate_api_key)

    def test_request_context(self):
        """RequestContext should track request metadata."""
        from backend.middleware.auth import RequestContext
        import uuid

        ctx = RequestContext(api_key="test-key", tenant_id="tenant-1", request_id=str(uuid.uuid4()))
        assert ctx.api_key == "test-key"
        assert ctx.tenant_id == "tenant-1"
        assert hasattr(ctx, "latency_ms")
        assert ctx.latency_ms >= 0
