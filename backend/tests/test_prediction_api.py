import asyncio
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from starlette.requests import Request
from starlette.responses import Response

import app as propintel_app
from app import (
    LoginInput,
    PropertyInput,
    RecommendInput,
    RegisterInput,
    ResetPasswordInput,
)
from auth_security import create_access_token


class StubPredictor:
    def predict(self, payload):
        return {
            "predicted_price": 9_000_000,
            "predicted_price_per_sqft": 10_000,
            "listed_price": payload["listed_price"],
            "delta_pct": None,
            "verdict": None,
            "confidence_score": None,
            "limitations": [],
            "is_reliable": True,
            "reliability_warnings": [],
        }


class StubExplainer:
    def explain(self, payload, top_k=7):
        return {"contributions": []}


class AuthApiTests(unittest.TestCase):
    USER_ID = "507f1f77bcf86cd799439011"

    @staticmethod
    def request(method="POST", headers=None):
        return Request(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": method,
                "scheme": "http",
                "path": "/api/auth/test",
                "raw_path": b"/api/auth/test",
                "query_string": b"",
                "headers": [
                    (key.lower().encode(), value.encode())
                    for key, value in (headers or {}).items()
                ],
                "client": ("127.0.0.1", 12345),
                "server": ("testserver", 80),
            }
        )

    @staticmethod
    def legacy_hash(password):
        import base64
        import hashlib

        salt = b"legacy-salt-1234"
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000, dklen=32)
        salt_text = base64.urlsafe_b64encode(salt).decode().rstrip("=")
        digest_text = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        return f"pbkdf2_sha256$310000${salt_text}${digest_text}"

    def test_registration_creates_argon2_user_and_starts_authenticated_session(self):
        with (
            patch.object(propintel_app, "_enforce_rate_limit"),
            patch.object(propintel_app.database, "create_user", return_value=self.USER_ID) as create_user,
            patch.object(propintel_app.database, "create_refresh_session") as create_session,
        ):
            response = Response()
            result = propintel_app.register(
                RegisterInput(
                    name=" Buyer ",
                    email=" BUYER@example.com ",
                    password="MapleHouse!2034",
                    remember=False,
                ),
                self.request(),
                response,
            )

        document = create_user.call_args.args[0]
        self.assertEqual(document["email"], "buyer@example.com")
        self.assertTrue(document["password_hash"].startswith("$argon2id$"))
        self.assertNotIn("MapleHouse!2034", str(document))
        self.assertNotIn("email_verified", document)
        self.assertEqual(result["user"]["id"], self.USER_ID)
        self.assertEqual(result["message"], "Account created successfully.")
        self.assertIn("access_token", result)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertFalse(create_session.call_args.args[0]["remember"])

    def test_invalid_registration_email_and_weak_password_are_rejected(self):
        with self.assertRaises(ValueError):
            RegisterInput(name="Buyer", email="invalid", password="MapleHouse!2034")
        with self.assertRaises(ValueError):
            RegisterInput(name="Buyer", email="buyer@example.com", password="weak")

    def test_duplicate_registration_returns_conflict_without_exposing_database_details(self):
        from database import UserAlreadyExists

        with (
            patch.object(propintel_app, "_enforce_rate_limit"),
            patch.object(
                propintel_app.database,
                "create_user",
                side_effect=UserAlreadyExists("duplicate"),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                propintel_app.register(
                    RegisterInput(
                        name="Buyer",
                        email="buyer@example.com",
                        password="MapleHouse!2034",
                    ),
                    self.request(),
                    Response(),
                )
        self.assertEqual(raised.exception.status_code, 409)

    def test_legacy_password_login_migrates_hash_and_returns_jwt_and_http_only_cookie(self):
        password = "ExistingPassword!2025"
        user = {
            "id": self.USER_ID,
            "name": "Buyer",
            "email": "buyer@example.com",
            "password_hash": self.legacy_hash(password),
            "email_verified": False,
            "role": "user",
        }
        response = Response()
        with (
            patch.object(propintel_app, "_enforce_rate_limit"),
            patch.object(propintel_app.database, "get_user", return_value=user),
            patch.object(propintel_app.database, "update_password_hash") as update_hash,
            patch.object(propintel_app.database, "create_refresh_session"),
        ):
            result = propintel_app.login(
                LoginInput(email=" Buyer@Example.com ", password=password),
                self.request(),
                response,
            )

        migrated_hash = update_hash.call_args.args[1]
        self.assertTrue(migrated_hash.startswith("$argon2id$"))
        self.assertNotIn(password, migrated_hash)
        self.assertEqual(result["user"]["id"], self.USER_ID)
        self.assertEqual(result["user"]["email"], "buyer@example.com")
        self.assertNotIn("password_hash", result["user"])
        self.assertIn("HttpOnly", response.headers["set-cookie"])

    def test_legacy_unverified_account_can_log_in_immediately(self):
        user = {
            "id": self.USER_ID,
            "name": "Buyer",
            "email": "buyer@example.com",
            "password_hash": propintel_app.hash_password("MapleHouse!2034"),
            "email_verified": False,
            "role": "user",
        }
        response = Response()
        with (
            patch.object(propintel_app, "_enforce_rate_limit"),
            patch.object(propintel_app.database, "get_user", return_value=user),
            patch.object(propintel_app.database, "create_refresh_session"),
        ):
            result = propintel_app.login(
                LoginInput(email="buyer@example.com", password="MapleHouse!2034"),
                self.request(),
                response,
            )

        self.assertIn("access_token", result)
        self.assertIn("HttpOnly", response.headers["set-cookie"])

    def test_login_rejects_an_incorrect_password(self):
        user = {
            "id": self.USER_ID,
            "email": "buyer@example.com",
            "password_hash": propintel_app.hash_password("CorrectHouse!2035"),
        }
        with (
            patch.object(propintel_app, "_enforce_rate_limit"),
            patch.object(propintel_app.database, "get_user", return_value=user),
        ):
            with self.assertRaises(HTTPException) as raised:
                propintel_app.login(
                    LoginInput(email="buyer@example.com", password="WrongHouse!2035"),
                    self.request(),
                    Response(),
                )
        self.assertEqual(raised.exception.status_code, 401)

    def test_protected_identity_uses_database_identity_without_verification_gate(self):
        token = create_access_token(
            self.USER_ID,
            "attacker@example.com",
            "admin",
            propintel_app.AUTH_SECRET.decode(),
            "token-id",
            int(time.time()),
        )
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with patch.object(
            propintel_app.database,
            "get_user_by_id",
            return_value={
                "id": self.USER_ID,
                "email": "buyer@example.com",
                "name": "Buyer",
                "email_verified": True,
                "role": "user",
            },
        ):
            self.assertEqual(propintel_app.require_auth(credentials), "buyer@example.com")
            with self.assertRaises(HTTPException) as forbidden:
                propintel_app.require_admin(credentials)
        self.assertEqual(forbidden.exception.status_code, 403)

        with patch.object(
            propintel_app.database,
            "get_user_by_id",
            return_value={
                "id": self.USER_ID,
                "email": "legacy@example.com",
                "name": "Legacy Buyer",
                "email_verified": False,
                "role": "user",
            },
        ):
            self.assertEqual(propintel_app.require_auth(credentials), "legacy@example.com")

    def test_refresh_rotates_session_and_rejects_reuse(self):
        refresh_token = "opaque-refresh-token"
        csrf = propintel_app._csrf_token(refresh_token)
        old_session = {
            "_id": propintel_app._token_hash("refresh", refresh_token),
            "user_id": self.USER_ID,
            "family_id": "session-family",
            "remember": True,
        }
        headers = {
            "Origin": propintel_app.ALLOWED_ORIGINS[0],
            "Cookie": f"{propintel_app._refresh_cookie_name()}={refresh_token}",
            "X-CSRF-Token": csrf,
        }
        response = Response()
        with (
            patch.object(propintel_app, "ALLOWED_ORIGINS", [headers["Origin"]]),
            patch.object(
                propintel_app.database,
                "rotate_refresh_session",
                return_value=("rotated", old_session),
            ) as rotate,
            patch.object(
                propintel_app.database,
                "get_user_by_id",
                return_value={
                    "id": self.USER_ID,
                    "email": "buyer@example.com",
                    "name": "Buyer",
                    "role": "user",
                },
            ),
        ):
            rotated = propintel_app.refresh_session(self.request(headers=headers), response)

        self.assertEqual(rotated["user"]["email"], "buyer@example.com")
        self.assertNotEqual(
            propintel_app._token_hash("refresh", refresh_token),
            rotate.call_args.args[1]["_id"],
        )
        self.assertIn("HttpOnly", response.headers["set-cookie"])

        with (
            patch.object(propintel_app, "ALLOWED_ORIGINS", [headers["Origin"]]),
            patch.object(propintel_app.database, "rotate_refresh_session", return_value=("reuse", None)),
        ):
            with self.assertRaises(HTTPException) as reused:
                propintel_app.refresh_session(self.request(headers=headers), Response())
        self.assertEqual(reused.exception.status_code, 401)

    def test_refresh_rejects_missing_or_invalid_csrf(self):
        refresh_token = "opaque-refresh-token"
        request = self.request(
            headers={
                "Origin": propintel_app.ALLOWED_ORIGINS[0],
                "Cookie": f"{propintel_app._refresh_cookie_name()}={refresh_token}",
                "X-CSRF-Token": "invalid",
            }
        )
        with self.assertRaises(HTTPException) as raised:
            propintel_app.refresh_session(request, Response())
        self.assertEqual(raised.exception.status_code, 403)

    def test_logout_revokes_refresh_session_and_clears_cookie(self):
        refresh_token = "opaque-refresh-token"
        headers = {
            "Origin": propintel_app.ALLOWED_ORIGINS[0],
            "Cookie": f"{propintel_app._refresh_cookie_name()}={refresh_token}",
            "X-CSRF-Token": propintel_app._csrf_token(refresh_token),
        }
        response = Response()
        with (
            patch.object(propintel_app, "ALLOWED_ORIGINS", [headers["Origin"]]),
            patch.object(propintel_app.database, "revoke_refresh_session") as revoke,
        ):
            result = propintel_app.logout(self.request(headers=headers), response)
        self.assertTrue(result["ok"])
        revoke.assert_called_once_with(
            propintel_app._token_hash("refresh", refresh_token),
            unittest.mock.ANY,
        )
        self.assertIn("Max-Age=0", response.headers["set-cookie"])

    def test_password_reset_returns_no_token_and_hands_hash_to_atomic_database_operation(self):
        with (
            patch.object(propintel_app, "_enforce_rate_limit"),
            patch.object(
                propintel_app.database,
                "consume_password_reset",
                return_value=self.USER_ID,
            ) as consume_reset,
        ):
            result = propintel_app.reset_password(
                ResetPasswordInput(token="r" * 40, new_password="NewHouse!2035"),
                self.request(),
            )
        self.assertNotIn("token", str(result))
        token_hash, password_hash, _ = consume_reset.call_args.args
        self.assertEqual(token_hash, propintel_app._token_hash("password-reset", "r" * 40))
        self.assertTrue(password_hash.startswith("$argon2id$"))
        self.assertTrue(propintel_app.verify_password("NewHouse!2035", password_hash))

    def test_forgot_password_is_generic_when_email_delivery_is_not_configured(self):
        with (
            patch.object(propintel_app, "_enforce_rate_limit"),
            patch.object(propintel_app, "email_delivery_configured", return_value=False),
            patch.object(propintel_app.database, "get_user") as get_user,
        ):
            result = propintel_app.forgot_password(
                propintel_app.EmailInput(email="buyer@example.com"),
                self.request(),
            )
        get_user.assert_not_called()
        self.assertIn("SMTP_HOST", result["message"])
        self.assertIn("EMAIL_FROM", result["message"])
        self.assertNotIn("token", str(result).lower())

    def test_forgot_password_sends_a_hashed_single_use_reset_link(self):
        user = {"id": self.USER_ID, "email": "buyer@example.com"}
        with (
            patch.object(propintel_app, "_enforce_rate_limit"),
            patch.object(propintel_app, "email_delivery_configured", return_value=True),
            patch.object(propintel_app.database, "get_user", return_value=user),
            patch.object(propintel_app.database, "create_password_reset") as create_reset,
            patch.object(propintel_app, "send_email") as send_email,
        ):
            result = propintel_app.forgot_password(
                propintel_app.EmailInput(email="buyer@example.com"),
                self.request(),
            )

        self.assertNotIn("token", str(result).lower())
        reset_token = send_email.call_args.args[2].split("token=")[1].split()[0]
        self.assertEqual(
            create_reset.call_args.args[0],
            propintel_app._token_hash("password-reset", reset_token),
        )
        self.assertEqual(create_reset.call_args.args[1], self.USER_ID)

    def test_email_verification_routes_are_removed(self):
        routes = {route.path for route in propintel_app.app.routes}
        self.assertNotIn("/api/auth/verify-email", routes)
        self.assertNotIn("/api/auth/resend-verification", routes)


class PredictionHistoryApiTests(unittest.TestCase):
    def setUp(self):
        self.original_state = propintel_app.STATE.copy()
        propintel_app.STATE.update(
            {
                "ready": True,
                "catalog": pd.DataFrame(
                    [{"city": "Mumbai", "locality": "Taloja"}]
                ),
                "predictor": StubPredictor(),
                "explainer": StubExplainer(),
            }
        )
        self.payload = PropertyInput(
            city="Mumbai",
            locality="Taloja",
            property_type="Residential Apartment",
            bhk=2,
            area_sqft=900,
            floor=4,
            total_floors=10,
        )

    def tearDown(self):
        propintel_app.STATE.clear()
        propintel_app.STATE.update(self.original_state)

    def test_saving_history_persists_authenticated_owner_and_prediction(self):
        with patch.object(propintel_app.database, "save_prediction", return_value="record-1") as save:
            response = propintel_app.save_prediction_history(
                self.payload,
                user_email="buyer@example.com",
            )

        saved = save.call_args.args[0]
        self.assertEqual(saved["user_email"], "buyer@example.com")
        self.assertEqual(saved["prediction"]["predicted_price"], 9_000_000)
        self.assertEqual(response["id"], "record-1")
        self.assertEqual(response["input"]["property_type"], "Apartment")
        self.assertTrue(response["created_at"].endswith("+00:00"))

    def test_history_reads_are_scoped_to_the_authenticated_owner(self):
        with patch.object(
            propintel_app.database,
            "get_predictions",
            side_effect=lambda email, limit: [{"id": email}],
        ) as get_predictions:
            first = propintel_app.get_prediction_history(
                user_email="first@example.com",
                limit=10,
            )
            second = propintel_app.get_prediction_history(
                user_email="second@example.com",
                limit=10,
            )

        self.assertEqual(first["results"], [{"id": "first@example.com"}])
        self.assertEqual(second["results"], [{"id": "second@example.com"}])
        get_predictions.assert_any_call("first@example.com", 10)
        get_predictions.assert_any_call("second@example.com", 10)


class RuntimeSafetyTests(unittest.TestCase):
    def setUp(self):
        self.original_state = propintel_app.STATE.copy()

    def tearDown(self):
        propintel_app.STATE.clear()
        propintel_app.STATE.update(self.original_state)

    def test_production_requires_a_configured_signing_secret(self):
        with (
            patch.object(propintel_app, "IS_PRODUCTION", True),
            patch.object(propintel_app, "JWT_SECRET_KEY", ""),
        ):
            with self.assertRaisesRegex(RuntimeError, "JWT_SECRET_KEY"):
                propintel_app._validate_runtime_configuration()

    def test_development_also_rejects_missing_or_short_signing_secret(self):
        with (
            patch.object(propintel_app, "IS_PRODUCTION", False),
            patch.object(propintel_app, "JWT_SECRET_KEY", "short-secret"),
        ):
            with self.assertRaisesRegex(RuntimeError, "JWT_SECRET_KEY"):
                propintel_app._validate_runtime_configuration()

    def test_application_lifespan_bootstraps_and_closes_database(self):
        async def run_lifespan():
            async with propintel_app.lifespan(propintel_app.app):
                pass

        with (
            patch.object(propintel_app, "_bootstrap_state") as bootstrap,
            patch.object(propintel_app.database, "connect") as connect,
            patch.object(propintel_app.database, "close") as close,
        ):
            asyncio.run(run_lifespan())

        bootstrap.assert_called_once_with()
        connect.assert_called_once_with()
        close.assert_called_once_with()

    def test_production_allows_registered_users_without_demo_admin(self):
        with (
            patch.object(propintel_app, "IS_PRODUCTION", True),
            patch.object(propintel_app, "JWT_SECRET_KEY", "s" * 32),
            patch.object(propintel_app, "AUTH_SECRET", b"s" * 32),
            patch.object(propintel_app, "AUTH_EMAIL", None),
            patch.object(propintel_app, "AUTH_PASSWORD", None),
            patch.object(propintel_app, "ALLOWED_ORIGINS", ["https://app.example.com"]),
        ):
            propintel_app._validate_runtime_configuration()

    def test_login_does_not_use_demo_credentials_when_admin_is_disabled(self):
        with (
            patch.object(propintel_app, "AUTH_EMAIL", None),
            patch.object(propintel_app, "AUTH_PASSWORD", None),
            patch.object(propintel_app.database, "get_user", return_value=None),
        ):
            with self.assertRaises(HTTPException) as raised:
                propintel_app.login(
                    propintel_app.LoginInput(
                        email="analyst@propintel.in",
                        password="propintel-demo",
                    )
                )
        self.assertEqual(raised.exception.status_code, 401)

    def test_malformed_bearer_token_returns_401(self):
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="not-a-valid-token",
        )
        with self.assertRaises(HTTPException) as raised:
            propintel_app.require_auth(credentials)
        self.assertEqual(raised.exception.status_code, 401)

    def test_missing_model_artifact_does_not_trigger_startup_retraining(self):
        with TemporaryDirectory() as directory:
            artifact_path = Path(directory) / "existing-model.joblib"
            artifact_path.write_text("preserve", encoding="utf-8")
            with (
                patch.object(propintel_app, "MODEL_PATH", artifact_path),
                patch.object(propintel_app, "load_saved_predictor", return_value=None),
            ):
                with self.assertLogs("propintel.api", level="ERROR"):
                    propintel_app._bootstrap_state()

            self.assertEqual(artifact_path.read_text(encoding="utf-8"), "preserve")
            self.assertFalse(propintel_app.STATE.get("ready"))

    def test_health_hides_internal_startup_error_and_reports_degraded_database(self):
        propintel_app.STATE.update(
            {
                "ready": False,
                "startup_error": "private traceback and filesystem path",
            }
        )
        with patch.object(propintel_app.database, "health_status", return_value="not_configured"):
            result = propintel_app.health()

        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["ml_engine"], "unavailable")
        self.assertNotIn("startup_error", str(result))
        self.assertNotIn("private traceback", str(result))

    def test_market_snapshot_contains_real_counts_without_forecast_data(self):
        propintel_app.STATE.update(
            {
                "ready": True,
                "catalog": pd.DataFrame(
                    [
                        {"city": "Mumbai", "price_per_sqft": 10_000, "bhk": 1},
                        {"city": "Mumbai", "price_per_sqft": 20_000, "bhk": 2},
                        {"city": "Pune", "price_per_sqft": 5_000, "bhk": 2},
                    ]
                ),
            }
        )

        result = propintel_app.market_trends(city="mumbai")

        self.assertEqual(result["total_properties"], 2)
        self.assertEqual(result["average_price_per_sqft"], 15_000)
        self.assertEqual(result["bhk_distribution"], {"1": 1, "2": 1})
        self.assertEqual(result["forecast"], {})

    def test_recommendation_api_preserves_budget_filters_and_total_match_count(self):
        class StubRecommender:
            def recommend_with_count(self, prefs, top_n):
                self.prefs = prefs
                self.top_n = top_n
                return ([{"listed_price": 7_500_000, "fair_price": 8_000_000}], 14)

        recommender = StubRecommender()
        propintel_app.STATE.update(
            {
                "ready": True,
                "catalog": pd.DataFrame(
                    [{"city": "Mumbai", "property_type": "Apartment"}]
                ),
                "recommender": recommender,
            }
        )

        result = propintel_app.recommend(
            RecommendInput(
                city="Mumbai",
                bhk=2,
                budget_min=5_000_000,
                budget_max=10_000_000,
            ),
            _=None,
        )

        self.assertEqual(result["count"], 14)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(recommender.prefs["budget_min"], 5_000_000)
        self.assertEqual(recommender.prefs["budget_max"], 10_000_000)
        self.assertEqual(recommender.top_n, 6)

    def test_listing_api_filters_actual_catalog_with_case_insensitive_locality_and_pagination(self):
        catalog = pd.DataFrame(
            [
                {"id": "a", "city": "Mumbai", "locality": "Aarey Milk Colony", "property_type": "Apartment", "bhk": 3, "area_sqft": 1800, "listed_price": 16_500_000, "furnishing": "Unfurnished"},
                {"id": "b", "city": "Mumbai", "locality": "Aarey Milk Colony", "property_type": "Apartment", "bhk": 2, "area_sqft": 2200, "listed_price": 39_000_000, "furnishing": "Unfurnished"},
                {"id": "c", "city": "Mumbai", "locality": "Powai", "property_type": "Villa", "bhk": 2, "area_sqft": 2200, "listed_price": 40_000_000, "furnishing": "Furnished"},
                {"id": "d", "city": "Mumbai", "locality": "Powai", "property_type": "Apartment", "bhk": 1, "area_sqft": 900, "listed_price": 8_000_000, "furnishing": "Unfurnished"},
            ]
        )
        propintel_app.STATE.update({"ready": True, "catalog": catalog})

        base = {
            "_": "test",
            "locality": None,
            "property_type": None,
            "bhk": None,
            "budget_max": None,
            "area_min": 0,
            "search": None,
            "limit": 24,
            "offset": 0,
        }
        all_results = propintel_app.get_listings(**base)
        aarey_results = propintel_app.get_listings(**{**base, "locality": "aArEy mIlK cOlOnY"})
        budget_results = propintel_app.get_listings(**{**base, "budget_max": 39_000_000})
        area_results = propintel_app.get_listings(**{**base, "area_min": 2200})
        bhk_results = propintel_app.get_listings(**{**base, "bhk": 2})
        type_results = propintel_app.get_listings(**{**base, "property_type": "apartment"})
        combined_results = propintel_app.get_listings(
            **{
                **base,
                "locality": "Aarey Milk Colony",
                "property_type": "Apartment",
                "budget_max": 39_000_000,
                "area_min": 2200,
            }
        )
        paged_results = propintel_app.get_listings(**{**base, "limit": 2, "offset": 2})
        reset_results = propintel_app.get_listings(**base)

        self.assertEqual(all_results["count"], 4)
        self.assertEqual(aarey_results["count"], 2)
        self.assertEqual(budget_results["count"], 3)
        self.assertEqual(area_results["count"], 2)
        self.assertEqual(bhk_results["count"], 2)
        self.assertEqual(type_results["count"], 3)
        self.assertEqual(combined_results["count"], 1)
        self.assertEqual(combined_results["results"][0]["id"], "b")
        self.assertEqual(paged_results["count"], 4)
        self.assertEqual([row["id"] for row in paged_results["results"]], ["c", "d"])
        self.assertEqual(reset_results["count"], all_results["count"])

    def test_prediction_failure_does_not_return_internal_exception_text(self):
        class FailingPredictor:
            def predict(self, payload):
                raise RuntimeError("private implementation detail")

        propintel_app.STATE.update(
            {
                "ready": True,
                "catalog": pd.DataFrame([{"city": "Mumbai", "locality": "Taloja"}]),
                "predictor": FailingPredictor(),
                "explainer": StubExplainer(),
            }
        )
        payload = PropertyInput(
            city="Mumbai",
            locality="Taloja",
            property_type="Apartment",
            bhk=2,
            area_sqft=900,
        )

        with self.assertLogs("propintel.api", level="ERROR"):
            with self.assertRaises(HTTPException) as raised:
                propintel_app.calculate_prediction(payload)

        self.assertEqual(raised.exception.status_code, 500)
        self.assertNotIn("private implementation detail", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
