import base64
import logging

import pytest
import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa as crypto_rsa
from flask_dashboard.license_manager import (
    _load_pem_key,
    _parse_rsa_key,
    _parse_rsa_keys,
    load_keys,
    sanitize_key_pem,
)


@pytest.fixture
def rsa_keypair():
    """Generate a fast RSA test key pair."""
    pub, priv = rsa.newkeys(512)
    return pub, priv


@pytest.fixture
def rsa_pem_strings(rsa_keypair):
    """Return PKCS#1 PEM strings for test key pair."""
    pub, priv = rsa_keypair
    return pub.save_pkcs1().decode("utf-8"), priv.save_pkcs1().decode("utf-8")


def test_sanitize_key_pem_clean_string(rsa_pem_strings):
    pub_pem, _ = rsa_pem_strings
    sanitized = sanitize_key_pem(pub_pem)
    assert sanitized is not None
    assert sanitized.startswith("-----BEGIN RSA PUBLIC KEY-----")
    assert sanitized.endswith("-----END RSA PUBLIC KEY-----")


def test_sanitize_key_pem_escaped_newlines():
    raw = "-----BEGIN RSA PRIVATE KEY-----\\nMIIE...\\n-----END RSA PRIVATE KEY-----"
    sanitized = sanitize_key_pem(raw)
    assert sanitized is not None
    assert "\\n" not in sanitized
    assert "\n" in sanitized
    assert sanitized.startswith("-----BEGIN RSA PRIVATE KEY-----")
    assert sanitized.endswith("-----END RSA PRIVATE KEY-----")


def test_sanitize_key_pem_surrounding_quotes():
    raw_dq = '"-----BEGIN RSA PUBLIC KEY-----\\nMIIB...\\n-----END RSA PUBLIC KEY-----"'
    assert sanitize_key_pem(raw_dq) == "-----BEGIN RSA PUBLIC KEY-----\nMIIB...\n-----END RSA PUBLIC KEY-----"

    raw_sq = "'-----BEGIN RSA PUBLIC KEY-----\\nMIIB...\\n-----END RSA PUBLIC KEY-----'"
    assert sanitize_key_pem(raw_sq) == "-----BEGIN RSA PUBLIC KEY-----\nMIIB...\n-----END RSA PUBLIC KEY-----"

    raw_nested = '  "\'-----BEGIN RSA PUBLIC KEY-----\\nMIIB...\\n-----END RSA PUBLIC KEY-----\'"  '
    assert sanitize_key_pem(raw_nested) == "-----BEGIN RSA PUBLIC KEY-----\nMIIB...\n-----END RSA PUBLIC KEY-----"


def test_sanitize_key_pem_collapsed_single_line(rsa_pem_strings):
    _, priv_pem = rsa_pem_strings
    # Collapse multi-line PEM into a single line with spaces instead of newlines
    collapsed = " ".join(priv_pem.split())
    sanitized = sanitize_key_pem(collapsed)
    assert sanitized is not None
    lines = sanitized.splitlines()
    assert lines[0] == "-----BEGIN RSA PRIVATE KEY-----"
    assert lines[-1] == "-----END RSA PRIVATE KEY-----"
    # Verify body is wrapped
    for line in lines[1:-1]:
        assert len(line) <= 64

    # Confirm key can be parsed
    key = rsa.PrivateKey.load_pkcs1(sanitized.encode())
    assert key is not None


def test_sanitize_key_pem_base64_encoded_fallback(rsa_pem_strings):
    _, priv_pem = rsa_pem_strings
    b64_encoded = base64.b64encode(priv_pem.encode("utf-8")).decode("utf-8")
    assert not b64_encoded.startswith("-----BEGIN")

    sanitized = sanitize_key_pem(b64_encoded)
    assert sanitized is not None
    assert sanitized.startswith("-----BEGIN RSA PRIVATE KEY-----")
    key = rsa.PrivateKey.load_pkcs1(sanitized.encode())
    assert key is not None


def test_sanitize_key_pem_none_and_empty():
    assert sanitize_key_pem(None) is None
    assert sanitize_key_pem("") is None
    assert sanitize_key_pem("   \n \t ") is None


def test_parse_rsa_keys_pkcs1(rsa_pem_strings):
    pub_pem, priv_pem = rsa_pem_strings
    keys = _parse_rsa_keys(pub_pem, priv_pem)
    assert keys is not None
    pub, priv = keys
    msg = b"render licensing test"
    sig = rsa.sign(msg, priv, "SHA-256")
    rsa.verify(msg, sig, pub)


def test_parse_rsa_keys_pkcs8_and_spki():
    crypto_key = crypto_rsa.generate_private_key(public_exponent=65537, key_size=1024)
    pkcs8_priv = crypto_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    spki_pub = crypto_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    # Escaped as single-line Render env var with quotes
    escaped_priv = '"' + pkcs8_priv.replace("\n", "\\n") + '"'
    escaped_pub = '"' + spki_pub.replace("\n", "\\n") + '"'

    keys = _parse_rsa_keys(escaped_pub, escaped_priv)
    assert keys is not None
    pub, priv = keys
    msg = b"render pkcs8 test"
    sig = rsa.sign(msg, priv, "SHA-256")
    rsa.verify(msg, sig, pub)


def test_parse_rsa_key_invalid_raises():
    with pytest.raises(ValueError):
        _parse_rsa_key("invalid public", is_private=False)
    with pytest.raises(ValueError):
        _parse_rsa_key("invalid private", is_private=True)


def test_load_pem_key_helper(tmp_path, monkeypatch, rsa_pem_strings):
    pub_pem, priv_pem = rsa_pem_strings

    # 1. Test from explicit path env var
    custom_file = tmp_path / "custom_priv.pem"
    custom_file.write_text(priv_pem)
    monkeypatch.setenv("LICENSE_PRIVATE_KEY_PATH", str(custom_file))
    loaded = _load_pem_key("LICENSE_PRIVATE_KEY_PEM", "license_private_key.pem")
    assert loaded == priv_pem

    monkeypatch.delenv("LICENSE_PRIVATE_KEY_PATH", raising=False)

    # 2. Test from environment variable
    monkeypatch.setenv("LICENSE_PUBLIC_KEY_PEM", pub_pem)
    loaded_pub = _load_pem_key("LICENSE_PUBLIC_KEY_PEM", "non_existent_file.pem")
    assert loaded_pub == pub_pem


def test_load_keys_from_secret_files(tmp_path, rsa_pem_strings, caplog):
    pub_pem, priv_pem = rsa_pem_strings
    priv_file = tmp_path / "license_private_key.pem"
    pub_file = tmp_path / "license_public_key.pem"
    priv_file.write_text(priv_pem)
    pub_file.write_text(pub_pem)

    with caplog.at_level(logging.INFO):
        keys = load_keys(secret_file_pairs=[(priv_file, pub_file)])

    assert keys is not None
    pub, priv = keys
    assert pub.n == rsa.PublicKey.load_pkcs1(pub_pem.encode()).n
    assert priv.n == rsa.PrivateKey.load_pkcs1(priv_pem.encode()).n
    assert "Loaded RSA licensing keys from Render Secret Files" in caplog.text


def test_load_keys_from_env_vars_single_line_escaped(monkeypatch, rsa_pem_strings, caplog):
    pub_pem, priv_pem = rsa_pem_strings
    escaped_priv = '"' + priv_pem.replace("\n", "\\n") + '"'
    escaped_pub = '"' + pub_pem.replace("\n", "\\n") + '"'

    monkeypatch.setenv("LICENSE_PRIVATE_KEY_PEM", escaped_priv)
    monkeypatch.setenv("LICENSE_PUBLIC_KEY_PEM", escaped_pub)

    with caplog.at_level(logging.INFO):
        keys = load_keys(secret_file_pairs=[])

    assert keys is not None
    pub, priv = keys
    assert pub.n == rsa.PublicKey.load_pkcs1(pub_pem.encode()).n
    assert priv.n == rsa.PrivateKey.load_pkcs1(priv_pem.encode()).n
    assert "Loaded RSA licensing keys from environment variables" in caplog.text


def test_load_keys_space_collapsed_env_vars(monkeypatch, rsa_pem_strings, caplog):
    pub_pem, priv_pem = rsa_pem_strings
    collapsed_priv = " ".join(priv_pem.split())
    collapsed_pub = " ".join(pub_pem.split())

    monkeypatch.setenv("LICENSE_PRIVATE_KEY_PEM", collapsed_priv)
    monkeypatch.setenv("LICENSE_PUBLIC_KEY_PEM", collapsed_pub)

    with caplog.at_level(logging.INFO):
        keys = load_keys(secret_file_pairs=[])

    assert keys is not None
    pub, priv = keys
    assert pub.n == rsa.PublicKey.load_pkcs1(pub_pem.encode()).n
    assert priv.n == rsa.PrivateKey.load_pkcs1(priv_pem.encode()).n
    assert "Loaded RSA licensing keys from environment variables" in caplog.text


def test_secret_files_precedence_over_env_vars(tmp_path, rsa_keypair, monkeypatch, caplog):
    pub1, priv1 = rsa_keypair
    pub2, priv2 = rsa.newkeys(512)

    priv_file = tmp_path / "license_private_key.pem"
    pub_file = tmp_path / "license_public_key.pem"
    priv_file.write_text(priv1.save_pkcs1().decode())
    pub_file.write_text(pub1.save_pkcs1().decode())

    # Set different keys in environment variables
    monkeypatch.setenv("LICENSE_PRIVATE_KEY_PEM", priv2.save_pkcs1().decode())
    monkeypatch.setenv("LICENSE_PUBLIC_KEY_PEM", pub2.save_pkcs1().decode())

    with caplog.at_level(logging.INFO):
        keys = load_keys(secret_file_pairs=[(priv_file, pub_file)])

    assert keys is not None
    pub, priv = keys
    # Must match secret files (pub1/priv1), NOT env vars (pub2/priv2)
    assert pub.n == pub1.n
    assert priv.n == priv1.n
    assert "Loaded RSA licensing keys from Render Secret Files" in caplog.text


def test_fallback_to_ephemeral_when_missing(monkeypatch, caplog):
    monkeypatch.delenv("LICENSE_PRIVATE_KEY_PEM", raising=False)
    monkeypatch.delenv("LICENSE_PUBLIC_KEY_PEM", raising=False)

    with caplog.at_level(logging.WARNING):
        keys = load_keys(secret_file_pairs=[])

    assert keys is not None
    pub, priv = keys
    assert isinstance(pub, rsa.PublicKey)
    assert isinstance(priv, rsa.PrivateKey)
    assert "Using generated ephemeral RSA keys for licensing" in caplog.text


def test_fallback_to_ephemeral_when_invalid(monkeypatch, caplog):
    monkeypatch.setenv("LICENSE_PRIVATE_KEY_PEM", "corrupt_data")
    monkeypatch.setenv("LICENSE_PUBLIC_KEY_PEM", "corrupt_data")

    with caplog.at_level(logging.WARNING):
        keys = load_keys(secret_file_pairs=[])

    assert keys is not None
    assert "Failed to parse provided RSA licensing keys" in caplog.text
    assert "Using generated ephemeral RSA keys for licensing" in caplog.text
