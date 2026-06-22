import pytest

from payments.auth import AuthError, decode_token


def test_decode_token_valid():
    assert decode_token("hdr.payload.sig") == "payload"


def test_decode_token_none():
    # A missing token must be rejected cleanly, not crash with AttributeError.
    with pytest.raises(AuthError):
        decode_token(None)
