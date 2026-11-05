import unittest
from datetime import datetime
from unittest.mock import MagicMock, Mock, patch

from pymongo.uri_parser import parse_uri

from database import MongoDatabase, _prepare_mongodb_uri


class MongoUriTests(unittest.TestCase):
    def test_raw_at_sign_in_password_is_encoded(self):
        uri = (
            "mongodb://test-user:p@ssword@localhost:27017/"
            "?directConnection=true"
        )

        prepared_uri = _prepare_mongodb_uri(uri)

        self.assertIn("p%40ssword@", prepared_uri)
        self.assertEqual(parse_uri(prepared_uri)["password"], "p@ssword")

    def test_already_encoded_credentials_are_not_double_encoded(self):
        uri = (
            "mongodb://test-user:p%40ssword@localhost:27017/"
            "?directConnection=true"
        )

        self.assertEqual(_prepare_mongodb_uri(uri), uri)
        self.assertEqual(parse_uri(uri)["password"], "p@ssword")

    def test_encoded_percent_is_not_double_encoded(self):
        uri = "mongodb://test-user:p%2540ss@localhost:27017/?directConnection=true"

        self.assertEqual(_prepare_mongodb_uri(uri), uri)
        self.assertEqual(parse_uri(uri)["password"], "p%40ss")

    def test_invalid_uri_without_recoverable_credentials_is_unchanged(self):
        uri = "not-a-mongodb-uri"

        self.assertEqual(_prepare_mongodb_uri(uri), uri)


class PredictionHistoryScopeTests(unittest.TestCase):
    def test_history_query_filters_by_owner_and_serializes_utc_datetime(self):
        database = MongoDatabase()
        cursor = Mock()
        cursor.sort.return_value = cursor
        cursor.limit.return_value = [
            {
                "_id": "record-1",
                "created_at": datetime(2025, 1, 2, 3, 4, 5),
                "prediction": {"predicted_price": 9_000_000},
            }
        ]
        collection = Mock()
        collection.find.return_value = cursor

        with patch.object(database, "_collection", return_value=collection):
            records = database.get_predictions("owner@example.com", 10)

        collection.find.assert_called_once_with(
            {"user_email": "owner@example.com"},
            {"user_email": 0},
        )
        cursor.sort.assert_called_once_with("created_at", -1)
        cursor.limit.assert_called_once_with(10)
        self.assertEqual(records[0]["id"], "record-1")
        self.assertEqual(records[0]["created_at"], "2025-01-02T03:04:05+00:00")


class UserPersistenceTests(unittest.TestCase):
    def test_new_user_persistence_does_not_create_email_verification_state(self):
        database = MongoDatabase()
        collection = Mock()
        collection.insert_one.return_value.inserted_id = "new-user-id"
        mongo_database = MagicMock()
        mongo_database.__getitem__.return_value = collection

        with patch.object(database, "_client_database", return_value=mongo_database):
            user_id = database.create_user(
                {
                    "name": "Buyer",
                    "email": "buyer@example.com",
                    "password_hash": "argon2-hash",
                }
            )

        self.assertEqual(user_id, "new-user-id")
        collection.insert_one.assert_called_once_with(
            {
                "name": "Buyer",
                "email": "buyer@example.com",
                "password_hash": "argon2-hash",
                "role": "user",
            }
        )


class AuthenticationTransactionTests(unittest.TestCase):
    def setUp(self):
        self.database = MongoDatabase()
        self.session = MagicMock()
        session_context = MagicMock()
        session_context.__enter__.return_value = self.session
        self.client = Mock()
        self.client.start_session.return_value = session_context
        self.collections = {
            "refresh_sessions": Mock(),
            "password_resets": Mock(),
            "users": Mock(),
        }
        mongo_database = MagicMock()
        mongo_database.client = self.client
        mongo_database.__getitem__.side_effect = self.collections.__getitem__
        self.session.with_transaction.side_effect = lambda operation: operation(self.session)
        self.database_patch = patch.object(
            self.database, "_client_database", return_value=mongo_database
        )
        self.database_patch.start()
        self.addCleanup(self.database_patch.stop)

    def test_refresh_rotation_inserts_complete_replacement_in_same_transaction(self):
        now = datetime(2025, 1, 2)
        previous = {
            "_id": "old-hash",
            "user_id": "user-123",
            "family_id": "family-123",
            "remember": False,
        }
        replacement = {
            "_id": "new-hash",
            "created_at": now,
            "expires_at": now,
        }
        self.collections["refresh_sessions"].find_one_and_update.return_value = previous

        state, old_session = self.database.rotate_refresh_session(
            "old-hash", replacement, now
        )

        self.assertEqual(state, "rotated")
        self.assertEqual(old_session, previous)
        self.collections["refresh_sessions"].insert_one.assert_called_once_with(
            {
                **replacement,
                "user_id": "user-123",
                "family_id": "family-123",
                "remember": False,
            },
            session=self.session,
        )
        self.session.with_transaction.assert_called_once()

    def test_password_reset_updates_password_and_revokes_sessions_atomically(self):
        now = datetime(2025, 1, 2)
        self.collections["password_resets"].find_one_and_delete.return_value = {
            "user_id": "507f1f77bcf86cd799439011"
        }
        self.collections["users"].update_one.return_value.matched_count = 1

        user_id = self.database.consume_password_reset("reset-hash", "new-hash", now)

        self.assertEqual(user_id, "507f1f77bcf86cd799439011")
        self.collections["users"].update_one.assert_called_once()
        self.collections["refresh_sessions"].update_many.assert_called_once_with(
            {"user_id": user_id, "revoked_at": {"$exists": False}},
            {"$set": {"revoked_at": now}},
            session=self.session,
        )
        self.session.with_transaction.assert_called_once()


if __name__ == "__main__":
    unittest.main()
