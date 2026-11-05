import base64
import hashlib
import time
import unittest
from jwt.exceptions import ExpiredSignatureError, InvalidSignatureError

from auth_security import (
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    decode_access_token,
    hash_password,
    normalize_email,
    password_needs_rehash,
    validate_new_password,
    verify_password,
)


class PasswordSecurityTests(unittest.TestCase):
    def test_argon2id_hash_verifies_without_storing_plaintext(self):
        password = "MapleHouse!2034"
        encoded = hash_password(password)

        self.assertTrue(encoded.startswith("$argon2id$"))
        self.assertNotIn(password, encoded)
        self.assertTrue(verify_password(password, encoded))
        self.assertFalse(verify_password("incorrect-password", encoded))
        self.assertFalse(password_needs_rehash(encoded))

    def test_legacy_pbkdf2_hash_is_verified_and_marked_for_migration(self):
        password = "ExistingPassword!2025"
        salt = b"legacy-salt-1234"
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000, dklen=32)
        salt_text = base64.urlsafe_b64encode(salt).decode().rstrip("=")
        digest_text = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        legacy_hash = f"pbkdf2_sha256$310000${salt_text}${digest_text}"

        self.assertTrue(verify_password(password, legacy_hash))
        self.assertFalse(verify_password("incorrect-password", legacy_hash))
        self.assertTrue(password_needs_rehash(legacy_hash))

    def test_new_password_policy_rejects_short_or_simple_passwords(self):
        for password in ("short7", "longpasswordonly", "123456789012"):
            with self.subTest(password=password), self.assertRaises(ValueError):
                validate_new_password(password)
        validate_new_password("MapleHouse!2034")

    def test_email_is_validated_and_normalized(self):
        self.assertEqual(normalize_email("  BUYER@Example.COM "), "buyer@example.com")
        with self.assertRaises(ValueError):
            normalize_email("not-an-email")


class JwtSecurityTests(unittest.TestCase):
    def setUp(self):
        self.secret = "s" * 48

    def token(self, issued_at=None):
        return create_access_token(
            "user-object-id",
            "buyer@example.com",
            "user",
            self.secret,
            "unique-token-id",
            int(time.time()) if issued_at is None else issued_at,
        )

    def test_jwt_has_required_identity_and_expiry_claims(self):
        now = int(time.time())
        claims = decode_access_token(self.token(now), self.secret)

        self.assertEqual(claims["sub"], "user-object-id")
        self.assertEqual(claims["email"], "buyer@example.com")
        self.assertEqual(claims["role"], "user")
        self.assertEqual(claims["iat"], now)
        self.assertEqual(claims["exp"] - claims["iat"], JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60)
        self.assertEqual(claims["jti"], "unique-token-id")

    def test_jwt_rejects_tampered_signature_and_expired_token(self):
        token = self.token()
        parts = token.split(".")
        signature = parts[2]
        parts[2] = ("A" if signature[0] != "A" else "B") + signature[1:]
        with self.assertRaises(InvalidSignatureError):
            decode_access_token(".".join(parts), self.secret)

        expired = self.token(int(time.time()) - JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60 - 1)
        with self.assertRaises(ExpiredSignatureError):
            decode_access_token(expired, self.secret)

    def test_jwt_rejects_a_different_signing_secret(self):
        with self.assertRaises(InvalidSignatureError):
            decode_access_token(self.token(), "x" * 48)


if __name__ == "__main__":
    unittest.main()
