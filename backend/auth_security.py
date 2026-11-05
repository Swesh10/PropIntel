"""Authentication primitives shared by the FastAPI authentication routes."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from dotenv import load_dotenv
from email_validator import EmailNotValidError, validate_email

load_dotenv(Path(__file__).with_name(".env"), override=False)

PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65_536, parallelism=2)
JWT_ISSUER = "propintel"
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
if JWT_ALGORITHM != "HS256":
    raise RuntimeError("JWT_ALGORITHM must be HS256.")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY") or os.getenv("PROPINTEL_AUTH_SECRET", "")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
)
if JWT_ACCESS_TOKEN_EXPIRE_MINUTES < 1:
    raise RuntimeError("JWT_ACCESS_TOKEN_EXPIRE_MINUTES must be positive.")


def normalize_email(value: str) -> str:
    try:
        return validate_email(value.strip(), check_deliverability=False).normalized.casefold()
    except (EmailNotValidError, AttributeError) as exc:
        raise ValueError("Enter a valid email address.") from exc


def validate_new_password(password: str) -> None:
    if not 12 <= len(password) <= 128:
        raise ValueError("Password must contain between 12 and 128 characters.")
    if not any(character.isalpha() for character in password) or not any(
        character.isdigit() or not character.isalnum() for character in password
    ):
        raise ValueError("Password must include letters and a number or symbol.")


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith("$argon2id$"):
        try:
            return PASSWORD_HASHER.verify(stored_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            return False

    try:
        algorithm, iterations_text, salt_text, expected_text = stored_hash.split("$", 3)
        iterations = int(iterations_text)
        if algorithm != "pbkdf2_sha256" or not 100_000 <= iterations <= 2_000_000:
            return False
        import base64
        import hashlib
        import hmac

        salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
        expected = base64.urlsafe_b64decode(
            expected_text + "=" * (-len(expected_text) % 4)
        )
        if len(salt) != 16 or len(expected) != 32:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations, dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except (AttributeError, TypeError, ValueError):
        return False


def password_needs_rehash(stored_hash: str) -> bool:
    return not stored_hash.startswith("$argon2id$")


def create_access_token(
    user_id: str,
    email: str,
    role: str,
    secret_key: str,
    jti: str,
    now: int,
) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "email": email,
            "role": role,
            "iat": now,
            "exp": now + JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            "jti": jti,
            "iss": JWT_ISSUER,
        },
        secret_key,
        algorithm=JWT_ALGORITHM,
    )


def decode_access_token(token: str, secret_key: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        secret_key,
        algorithms=[JWT_ALGORITHM],
        issuer=JWT_ISSUER,
        options={"require": ["sub", "iat", "exp", "jti", "iss"]},
    )


def send_email(recipient: str, subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST", "").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("EMAIL_FROM", "").strip()
    if not host or not sender:
        raise RuntimeError("Email delivery is not configured.")
    port = int(os.getenv("SMTP_PORT", "587"))
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    if bool(username) != bool(password):
        raise RuntimeError("Email delivery credentials are incomplete.")
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as smtp:
                if username:
                    smtp.login(username, password)
                smtp.send_message(message)
            return

        with smtplib.SMTP(host, port, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise RuntimeError("Email delivery failed.") from exc


def email_delivery_configured() -> bool:
    return bool(
        os.getenv("SMTP_HOST", "").strip()
        and os.getenv("EMAIL_FROM", "").strip()
        and bool(os.getenv("SMTP_USERNAME", "")) == bool(os.getenv("SMTP_PASSWORD", ""))
    )
