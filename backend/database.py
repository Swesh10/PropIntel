"""MongoDB access for optional PropIntel prediction history."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import quote_plus, unquote

from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import (
    ConfigurationError,
    ConnectionFailure,
    DuplicateKeyError,
    InvalidURI,
    NetworkTimeout,
    OperationFailure,
    PyMongoError,
    ServerSelectionTimeoutError,
)
from pymongo.uri_parser import parse_uri
from bson import ObjectId
from bson.errors import InvalidId

load_dotenv(Path(__file__).with_name(".env"), override=False)

logger = logging.getLogger("propintel.database")


def _prepare_mongodb_uri(uri: str) -> str:
    """Validate a URI and safely encode raw credentials when they break parsing."""
    try:
        parse_uri(uri)
        return uri
    except (ConfigurationError, InvalidURI):
        pass

    scheme_end = uri.find("://")
    if scheme_end < 0:
        return uri

    authority_start = scheme_end + 3
    authority_end = min(
        (
            position
            for delimiter in ("/", "?", "#")
            if (position := uri.find(delimiter, authority_start)) >= 0
        ),
        default=len(uri),
    )
    authority = uri[authority_start:authority_end]
    if "@" not in authority:
        return uri

    userinfo, host = authority.rsplit("@", 1)
    username, separator, password = userinfo.partition(":")
    if not separator or not username or not password:
        return uri

    normalized_userinfo = (
        f"{quote_plus(unquote(username), safe='')}:"
        f"{quote_plus(unquote(password), safe='')}"
    )
    normalized_uri = (
        uri[:authority_start]
        + normalized_userinfo
        + "@"
        + host
        + uri[authority_end:]
    )
    try:
        parse_uri(normalized_uri)
    except (ConfigurationError, InvalidURI):
        return uri
    return normalized_uri


class DatabaseUnavailable(RuntimeError):
    """Raised when a requested history operation cannot reach MongoDB."""


class UserAlreadyExists(RuntimeError):
    """Raised when a registration email is already in use."""


class MongoDatabase:
    def __init__(self) -> None:
        self._uri = _prepare_mongodb_uri(os.getenv("MONGODB_URI", "").strip())
        self._db_name = os.getenv("MONGODB_DB_NAME", "propintel").strip() or "propintel"
        self._client: MongoClient | None = None
        self._lock = Lock()
        self._diagnostic_code = "not_configured" if not self._uri else "not_checked"

    @property
    def configured(self) -> bool:
        return bool(self._uri)

    @property
    def diagnostic(self) -> str:
        messages = {
            "not_configured": "Set MONGODB_URI in backend/.env and restart the backend.",
            "not_checked": "MongoDB connection has not been tested yet.",
            "connected": "MongoDB ping succeeded.",
            "invalid_uri": (
                "MONGODB_URI is invalid. Copy the current connection string from Atlas, "
                "replace its placeholders, and percent-encode username and password separately "
                "with urllib.parse.quote_plus. Do not encode the complete URI."
            ),
            "authentication_failed": (
                "Atlas rejected database authentication. Verify the database user's name, "
                "password, and authentication permissions in Atlas."
            ),
            "atlas_rejected_request": (
                "Atlas rejected the database request. Check Network Access for this server's current public IP "
                "and verify the database user has access to the propintel database."
            ),
            "server_selection_timeout": (
                "MongoDB servers could not be reached. Check Atlas cluster status, Network Access "
                "IP allowlisting, DNS/SRV resolution, and outbound TLS access."
            ),
            "network_timeout": (
                "The connection timed out. Check Atlas Network Access, cluster status, DNS, and network access."
            ),
            "connection_failed": (
                "MongoDB connection failed. Check Atlas cluster status, Network Access, and DNS/TLS connectivity."
            ),
            "mongodb_error": (
                "MongoDB rejected the operation. Check database-user permissions and Atlas configuration."
            ),
        }
        return messages.get(self._diagnostic_code, messages["mongodb_error"])

    def _set_failure(self, error: BaseException) -> None:
        if isinstance(error, (InvalidURI, ConfigurationError)):
            code = "invalid_uri"
        elif isinstance(error, OperationFailure) and error.code == 18:
            code = "authentication_failed"
        elif isinstance(error, OperationFailure) and error.code == 8000:
            code = "atlas_rejected_request"
        elif isinstance(error, ServerSelectionTimeoutError):
            code = "server_selection_timeout"
        elif isinstance(error, NetworkTimeout):
            code = "network_timeout"
        elif isinstance(error, ConnectionFailure):
            code = "connection_failed"
        else:
            code = "mongodb_error"
        self._diagnostic_code = code
        logger.warning("MongoDB operation failed; diagnostic category: %s", code)

    def connect(self) -> None:
        if not self.configured:
            self._diagnostic_code = "not_configured"
            logger.info("MongoDB is not configured; prediction history is disabled.")
            return

        try:
            parse_uri(self._uri)
            with self._lock:
                if self._client is None:
                    self._client = MongoClient(
                        self._uri,
                        appname="PropIntel",
                        serverSelectionTimeoutMS=4000,
                        connectTimeoutMS=3000,
                    )
                client = self._client

            client.admin.command("ping")
            client[self._db_name]["prediction_history"].create_index(
                [("user_email", 1), ("created_at", DESCENDING)],
                name="user_created_at",
            )
            client[self._db_name]["users"].create_index(
                [("email", ASCENDING)],
                unique=True,
                name="email_unique",
            )
            client[self._db_name]["refresh_sessions"].create_index(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="refresh_session_expiry",
            )
            client[self._db_name]["password_resets"].create_index(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="password_reset_expiry",
            )
            client[self._db_name]["auth_rate_limits"].create_index(
                [("expires_at", ASCENDING)],
                expireAfterSeconds=0,
                name="auth_rate_limit_expiry",
            )
            self._diagnostic_code = "connected"
        except (PyMongoError, ValueError) as exc:
            self._set_failure(exc)

    def health_status(self) -> str:
        if not self.configured:
            self._diagnostic_code = "not_configured"
            return "not_configured"
        if self._client is None:
            self.connect()
        if self._client is None:
            return "unavailable"
        try:
            self._client.admin.command("ping")
            self._diagnostic_code = "connected"
        except PyMongoError as exc:
            self._set_failure(exc)
            return "unavailable"
        return "connected"

    def _collection(self) -> Collection:
        if not self.configured:
            raise DatabaseUnavailable("MongoDB is not configured.")
        if self._client is None:
            self.connect()
        if self._client is None:
            raise DatabaseUnavailable(self.diagnostic)
        return self._client[self._db_name]["prediction_history"]

    def save_prediction(self, document: dict[str, Any]) -> str:
        try:
            result = self._collection().insert_one(document)
        except PyMongoError as exc:
            self._set_failure(exc)
            raise DatabaseUnavailable(self.diagnostic) from exc
        return str(result.inserted_id)

    def get_predictions(self, user_email: str, limit: int) -> list[dict[str, Any]]:
        try:
            records = self._collection().find(
                {"user_email": user_email},
                {"user_email": 0},
            ).sort("created_at", DESCENDING).limit(limit)
            results = []
            for record in records:
                created_at = record["created_at"]
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                record["id"] = str(record.pop("_id"))
                record["created_at"] = created_at.isoformat()
                results.append(record)
            return results
        except PyMongoError as exc:
            self._set_failure(exc)
            raise DatabaseUnavailable(self.diagnostic) from exc

    def create_user(self, document: dict[str, Any]) -> str:
        try:
            result = self._client_database()["users"].insert_one(
                {**document, "role": document.get("role", "user")}
            )
            return str(result.inserted_id)
        except DuplicateKeyError as exc:
            raise UserAlreadyExists("An account with this email already exists.") from exc
        except PyMongoError as exc:
            self._set_failure(exc)
            raise DatabaseUnavailable(self.diagnostic) from exc

    def get_user(self, email: str) -> dict[str, Any] | None:
        try:
            user = self._client_database()["users"].find_one({"email": email})
            return self._serialize_user(user)
        except PyMongoError as exc:
            self._set_failure(exc)
            raise DatabaseUnavailable(self.diagnostic) from exc

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        try:
            user = self._client_database()["users"].find_one({"_id": ObjectId(user_id)})
            return self._serialize_user(user)
        except InvalidId:
            return None
        except PyMongoError as exc:
            self._set_failure(exc)
            raise DatabaseUnavailable(self.diagnostic) from exc

    @staticmethod
    def _serialize_user(user: dict[str, Any] | None) -> dict[str, Any] | None:
        if user is None:
            return None
        user["id"] = str(user.pop("_id"))
        return user

    def update_password_hash(self, user_id: str, password_hash: str) -> None:
        try:
            self._client_database()["users"].update_one(
                {"_id": ObjectId(user_id)},
                {"$set": {"password_hash": password_hash}},
            )
        except (InvalidId, PyMongoError) as exc:
            if isinstance(exc, PyMongoError):
                self._set_failure(exc)
                raise DatabaseUnavailable(self.diagnostic) from exc
            raise

    def create_refresh_session(self, document: dict[str, Any]) -> None:
        try:
            self._client_database()["refresh_sessions"].insert_one(document)
        except PyMongoError as exc:
            self._set_failure(exc)
            raise DatabaseUnavailable(self.diagnostic) from exc

    def rotate_refresh_session(
        self, old_hash: str, new_document: dict[str, Any], now: datetime
    ) -> tuple[str, dict[str, Any] | None]:
        try:
            database = self._client_database()
            collection = database["refresh_sessions"]

            def rotate(session: Any) -> tuple[str, dict[str, Any] | None]:
                previous = collection.find_one_and_update(
                    {
                        "_id": old_hash,
                        "revoked_at": {"$exists": False},
                        "expires_at": {"$gt": now},
                    },
                    {
                        "$set": {
                            "revoked_at": now,
                            "replaced_by": new_document["_id"],
                        }
                    },
                    return_document=ReturnDocument.BEFORE,
                    session=session,
                )
                if previous is None:
                    used = collection.find_one({"_id": old_hash}, session=session)
                    if used and used.get("revoked_at"):
                        collection.update_many(
                            {"family_id": used["family_id"]},
                            {"$set": {"revoked_at": now}},
                            session=session,
                        )
                        return "reuse", None
                    return "invalid", None

                collection.insert_one(
                    {
                        **new_document,
                        "user_id": previous["user_id"],
                        "family_id": previous["family_id"],
                        "remember": previous.get("remember", True),
                    },
                    session=session,
                )
                return "rotated", previous

            with database.client.start_session() as session:
                return session.with_transaction(rotate)
        except PyMongoError as exc:
            self._set_failure(exc)
            raise DatabaseUnavailable(self.diagnostic) from exc

    def get_active_refresh_session(self, token_hash: str, now: datetime) -> dict[str, Any] | None:
        try:
            return self._client_database()["refresh_sessions"].find_one(
                {
                    "_id": token_hash,
                    "revoked_at": {"$exists": False},
                    "expires_at": {"$gt": now},
                }
            )
        except PyMongoError as exc:
            self._set_failure(exc)
            raise DatabaseUnavailable(self.diagnostic) from exc

    def revoke_refresh_session(self, token_hash: str, now: datetime) -> None:
        try:
            self._client_database()["refresh_sessions"].update_one(
                {"_id": token_hash, "revoked_at": {"$exists": False}},
                {"$set": {"revoked_at": now}},
            )
        except PyMongoError as exc:
            self._set_failure(exc)
            raise DatabaseUnavailable(self.diagnostic) from exc

    def revoke_user_refresh_sessions(self, user_id: str, now: datetime) -> None:
        try:
            self._client_database()["refresh_sessions"].update_many(
                {"user_id": user_id, "revoked_at": {"$exists": False}},
                {"$set": {"revoked_at": now}},
            )
        except PyMongoError as exc:
            self._set_failure(exc)
            raise DatabaseUnavailable(self.diagnostic) from exc

    def consume_auth_rate_limit(
        self, key: str, max_attempts: int, window_seconds: int, now: datetime
    ) -> bool:
        bucket = int(now.timestamp()) // window_seconds
        bucket_id = f"{key}:{bucket}"
        try:
            collection = self._client_database()["auth_rate_limits"]
            update = {
                "$inc": {"attempts": 1},
                "$setOnInsert": {
                    "expires_at": now + timedelta(seconds=window_seconds * 2)
                },
            }
            try:
                record = collection.find_one_and_update(
                    {"_id": bucket_id},
                    update,
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                )
            except DuplicateKeyError:
                record = collection.find_one_and_update(
                    {"_id": bucket_id},
                    {"$inc": {"attempts": 1}},
                    return_document=ReturnDocument.AFTER,
                )
            return bool(record and record["attempts"] <= max_attempts)
        except PyMongoError as exc:
            self._set_failure(exc)
            raise DatabaseUnavailable(self.diagnostic) from exc

    def create_password_reset(self, token_hash: str, user_id: str, expires_at: datetime) -> None:
        try:
            self._client_database()["password_resets"].insert_one(
                {"_id": token_hash, "user_id": user_id, "expires_at": expires_at}
            )
        except PyMongoError as exc:
            self._set_failure(exc)
            raise DatabaseUnavailable(self.diagnostic) from exc

    def consume_password_reset(
        self, token_hash: str, password_hash: str, now: datetime
    ) -> str | None:
        try:
            database = self._client_database()
            resets = database["password_resets"]

            def reset(session: Any) -> str | None:
                record = resets.find_one_and_delete(
                    {"_id": token_hash, "expires_at": {"$gt": now}},
                    session=session,
                )
                if not record:
                    return None

                user_id = str(record["user_id"])
                updated = database["users"].update_one(
                    {"_id": ObjectId(user_id)},
                    {"$set": {"password_hash": password_hash}},
                    session=session,
                )
                if updated.matched_count != 1:
                    raise _PasswordResetUserNotFound

                database["refresh_sessions"].update_many(
                    {"user_id": user_id, "revoked_at": {"$exists": False}},
                    {"$set": {"revoked_at": now}},
                    session=session,
                )
                return user_id

            with database.client.start_session() as session:
                return session.with_transaction(reset)
        except _PasswordResetUserNotFound:
            return None
        except PyMongoError as exc:
            self._set_failure(exc)
            raise DatabaseUnavailable(self.diagnostic) from exc

    def _client_database(self) -> Database:
        if not self.configured:
            raise DatabaseUnavailable("MongoDB is not configured.")
        if self._client is None:
            self.connect()
        if self._client is None:
            raise DatabaseUnavailable(self.diagnostic)
        return self._client[self._db_name]

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None


database = MongoDatabase()


class _PasswordResetUserNotFound(Exception):
    pass
