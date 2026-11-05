"""
PropIntel :: app.py
-------------------------------------------------
FastAPI entrypoint. Boots the dataset, trains PropIntelPredictor on startup,
wires up XAIExplainer / WhatIfEngine / RecommendationEngine, and exposes the
REST surface consumed by the React frontend.

Run:
    uvicorn app:app --reload --port 8000
"""

from __future__ import annotations

import os
import hashlib
import hmac
import logging
import re
import secrets
from functools import lru_cache
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import joblib
import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator, model_validator
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
import uvicorn

from auth_security import (
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
    create_access_token,
    decode_access_token,
    email_delivery_configured,
    hash_password,
    normalize_email,
    password_needs_rehash,
    send_email,
    validate_new_password,
    verify_password,
)
from data_gen import AMENITIES_POOL
from database import DatabaseUnavailable, UserAlreadyExists, database
from ml_engine import (
    ALL_FEATURES,
    PropIntelPredictor,
    RecommendationEngine,
    WhatIfEngine,
    XAIExplainer,
    cross_validated_catalog_estimates,
    filter_properties_by_budget,
    prepare_mumbai_dataset,
    normalize_furnishing,
    normalize_property_type,
    variance_percentage,
)

# ---------------------------------------------------------------------------
# Global state + config
# ---------------------------------------------------------------------------
STATE: dict = {}
logger = logging.getLogger("propintel.api")
MODEL_PATH = Path(__file__).resolve().parent / "models" / "mumbai_model_v5.joblib"
AUTH_SCHEME = HTTPBearer(auto_error=False)
APP_ENV = os.getenv("PROPINTEL_ENV", "development").strip().casefold()
IS_PRODUCTION = APP_ENV not in {"dev", "development", "test"}
AUTH_SECRET = JWT_SECRET_KEY.encode("utf-8")
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))
PASSWORD_RESET_EXPIRE_MINUTES = int(
    os.getenv("PASSWORD_RESET_TOKEN_EXPIRE_MINUTES", "15")
)
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173").rstrip("/")
AUTH_EMAIL_VALUE = os.getenv("PROPINTEL_ADMIN_EMAIL")
AUTH_PASSWORD_VALUE = os.getenv("PROPINTEL_ADMIN_PASSWORD")
AUTH_EMAIL = (
    AUTH_EMAIL_VALUE.strip().lower()
    if AUTH_EMAIL_VALUE
    else None if IS_PRODUCTION else "analyst@propintel.in"
)
AUTH_PASSWORD = (
    AUTH_PASSWORD_VALUE
    if AUTH_PASSWORD_VALUE
    else None if IS_PRODUCTION else "propintel-demo"
)
_allowed_origins_value = os.getenv("PROPINTEL_ALLOWED_ORIGINS")
if _allowed_origins_value is None and not IS_PRODUCTION:
    _allowed_origins_value = "http://localhost:5173,http://127.0.0.1:5173"
ALLOWED_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in (_allowed_origins_value or "").split(",")
    if origin.strip()
]
PASSWORD_HASH_ITERATIONS = 310_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_saved_predictor() -> Optional[PropIntelPredictor]:
    if not MODEL_PATH.exists():
        return None
    artifact = joblib.load(MODEL_PATH)
    if (
        artifact.get("artifact_version") != 5
        or artifact.get("feature_columns") != ALL_FEATURES
        or not artifact.get("training_profile")
        or artifact.get("target_representation") not in {"total_price", "price_per_sqft"}
        or artifact.get("target_transform") not in {"none", "log1p"}
    ):
        logger.error("Saved model artifact is stale or incompatible.")
        return None
    pipeline = artifact["pipeline"]
    model_type = str(artifact.get("model_name", "xgboost")).lower().replace(" ", "_")
    model_type = {
        "randomforest": "random_forest",
        "gradientboosting": "gradient_boosting",
        "linearregression": "linear_regression",
    }.get(model_type.replace("_", ""), model_type)
    predictor = PropIntelPredictor(model_type=model_type)
    predictor.pipeline = pipeline
    predictor.preprocessor = pipeline.named_steps["preprocessor"]
    predictor.model = pipeline.named_steps["model"]
    predictor.is_fitted = True
    predictor.metrics = artifact.get("metrics", {})
    predictor.feature_columns = artifact.get("feature_columns", [])
    predictor.training_profile = artifact["training_profile"]
    predictor.target_representation = artifact["target_representation"]
    predictor._use_log_target = artifact.get("target_transform") == "log1p"
    return predictor


def _require_ready():
    """Raise 503 if the ML engine didn't boot successfully."""
    if not STATE.get("ready"):
        raise HTTPException(
            status_code=503,
            detail="Prediction services are temporarily unavailable.",
        )


def _validate_runtime_configuration() -> None:
    if len(JWT_SECRET_KEY.strip().encode("utf-8")) < 32:
        raise RuntimeError(
            "JWT_SECRET_KEY (or legacy PROPINTEL_AUTH_SECRET) must contain at least 32 bytes."
        )
    if not IS_PRODUCTION:
        return
    if JWT_ALGORITHM != "HS256":
        raise RuntimeError("JWT_ALGORITHM must be HS256.")
    if bool(AUTH_EMAIL) != bool(AUTH_PASSWORD):
        raise RuntimeError(
            "Configure both PROPINTEL_ADMIN_EMAIL and PROPINTEL_ADMIN_PASSWORD, or neither."
        )
    if AUTH_EMAIL and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", AUTH_EMAIL):
        raise RuntimeError("PROPINTEL_ADMIN_EMAIL must be a valid email address.")
    if AUTH_PASSWORD and len(AUTH_PASSWORD.strip()) < 12:
        raise RuntimeError("Production administrator passwords must be at least 12 characters.")
    if "*" in ALLOWED_ORIGINS:
        raise RuntimeError(
            "PROPINTEL_ALLOWED_ORIGINS cannot contain '*' when credentialed CORS is enabled."
        )
    if not email_delivery_configured():
        logger.warning(
            "SMTP is not configured; password-reset email delivery is unavailable."
        )


def _bootstrap_state():
    """Load the validated model artifact and catalog. Called at startup."""
    try:
        predictor = load_saved_predictor()
        if predictor is None:
            raise RuntimeError(
                "A compatible validated model artifact is required. "
                "Train and review a candidate offline before promoting it."
            )
        df = prepare_mumbai_dataset()
        df["model_estimate"] = cross_validated_catalog_estimates(predictor, df)

        explainer = XAIExplainer(predictor, df)
        what_if = WhatIfEngine(predictor)
        recommender = RecommendationEngine(predictor, df)

        STATE["catalog"] = df
        STATE["predictor"] = predictor
        STATE["explainer"] = explainer
        STATE["what_if"] = what_if
        STATE["recommender"] = recommender
        STATE["ready"] = True
        logger.info(
            "Model ready. R2=%.3f MAE=INR%.0f MAPE=%.2f%%",
            predictor.metrics.get("r2", 0),
            predictor.metrics.get("mae", 0),
            predictor.metrics.get("mape", 0),
        )
    except Exception:  # noqa: BLE001
        logger.exception("Model bootstrap failed.")
        STATE["ready"] = False
        STATE["startup_error"] = "See server logs for the startup failure."


# ---------------------------------------------------------------------------
# Lifespan (replaces deprecated @app.on_event)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        _validate_runtime_configuration()
        _bootstrap_state()
        database.connect()
        yield
    finally:
        database.close()


# ---------------------------------------------------------------------------
# App bootstrap
# ---------------------------------------------------------------------------
app = FastAPI(
    title="PropIntel API",
    description="AI-Powered Maharashtra Property Price Prediction & Insight Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class LoginInput(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=128)
    remember: bool = True

    @field_validator("email")
    @classmethod
    def normalize_login_email(cls, value: str) -> str:
        return normalize_email(value)


class RegisterInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=12, max_length=128)
    remember: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name cannot be blank.")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("password")
    @classmethod
    def enforce_password_policy(cls, value: str) -> str:
        validate_new_password(value)
        return value


class EmailInput(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email_value(cls, value: str) -> str:
        return normalize_email(value)


class ResetPasswordInput(BaseModel):
    token: str = Field(..., min_length=32, max_length=200)
    new_password: str = Field(..., min_length=12, max_length=128)

    @field_validator("new_password")
    @classmethod
    def enforce_password_policy(cls, value: str) -> str:
        validate_new_password(value)
        return value


def _token_hash(purpose: str, token: str) -> str:
    return hmac.new(
        AUTH_SECRET, f"{purpose}:{token}".encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _rate_limit_key(scope: str, value: str) -> str:
    return _token_hash("rate-limit", f"{scope}:{value}")


def _enforce_rate_limit(
    request: Request,
    scope: str,
    subject: str,
    max_attempts: int,
    window_seconds: int,
    ip_max_attempts: int | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    ip_address = request.client.host if request.client else "unknown"
    try:
        ip_allowed = database.consume_auth_rate_limit(
            _rate_limit_key(f"{scope}:ip", ip_address),
            ip_max_attempts or max_attempts,
            window_seconds,
            now,
        )
        subject_allowed = database.consume_auth_rate_limit(
            _rate_limit_key(f"{scope}:subject", subject),
            max_attempts,
            window_seconds,
            now,
        )
    except DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Authentication is temporarily unavailable."
        ) from exc
    if not ip_allowed or not subject_allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please wait before trying again.",
            headers={"Retry-After": str(window_seconds)},
        )


def _refresh_cookie_name() -> str:
    return "__Host-propintel_refresh" if IS_PRODUCTION else "propintel_refresh"


def _cookie_settings() -> dict:
    return {
        "httponly": True,
        "secure": IS_PRODUCTION,
        "samesite": "none" if IS_PRODUCTION else "lax",
        "path": "/",
    }


def _set_refresh_cookie(response: Response, token: str, remember: bool) -> None:
    options = _cookie_settings()
    if remember:
        options["max_age"] = REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
    response.set_cookie(_refresh_cookie_name(), token, **options)


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        _refresh_cookie_name(),
        path="/",
        secure=IS_PRODUCTION,
        httponly=True,
        samesite="none" if IS_PRODUCTION else "lax",
    )


def _csrf_token(refresh_token: str) -> str:
    return _token_hash("csrf", refresh_token)


def _require_trusted_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin or origin.rstrip("/") not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="Request origin is not allowed.")


def _require_csrf(request: Request, refresh_token: str) -> None:
    _require_trusted_origin(request)
    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied or not hmac.compare_digest(supplied, _csrf_token(refresh_token)):
        raise HTTPException(status_code=403, detail="CSRF validation failed.")


def _create_refresh_session(
    user_id: str,
    email: str,
    role: str,
    remember: bool = True,
    family_id: str | None = None,
) -> tuple[str, str, str]:
    now = datetime.now(timezone.utc)
    refresh_token = secrets.token_urlsafe(48)
    refresh_hash = _token_hash("refresh", refresh_token)
    family = family_id or secrets.token_urlsafe(24)
    database.create_refresh_session(
        {
            "_id": refresh_hash,
            "user_id": user_id,
            "family_id": family,
            "remember": remember,
            "created_at": now,
            "expires_at": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        }
    )
    access_token = create_access_token(
        user_id,
        email,
        role,
        AUTH_SECRET.decode("utf-8"),
        secrets.token_urlsafe(18),
        int(now.timestamp()),
    )
    return refresh_token, access_token, family


def _auth_response(
    response: Response,
    user_id: str,
    email: str,
    name: str,
    role: str,
    remember: bool,
    family_id: str | None = None,
) -> dict:
    try:
        refresh_token, access_token, _ = _create_refresh_session(
            user_id, email, role, remember, family_id
        )
    except DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Authentication is temporarily unavailable."
        ) from exc
    _set_refresh_cookie(response, refresh_token, remember)
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "csrf_token": _csrf_token(refresh_token),
        "user": {"id": user_id, "email": email, "name": name, "role": role},
    }


def _authenticated_identity(token: str) -> dict:
    try:
        claims = decode_access_token(token, AUTH_SECRET.decode("utf-8"))
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail="Authentication token is invalid or expired.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise HTTPException(status_code=401, detail="Invalid authentication token.")
    if subject.startswith("admin:"):
        email = subject.removeprefix("admin:")
        if not AUTH_EMAIL or not hmac.compare_digest(email, AUTH_EMAIL):
            raise HTTPException(status_code=401, detail="Invalid authentication token.")
        return {"id": subject, "email": email, "name": email, "role": "admin"}

    try:
        user = database.get_user_by_id(subject)
    except DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Authentication is temporarily unavailable."
        ) from exc
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Authentication account is unavailable.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    role = user.get("role", "user")
    if role not in {"user", "admin"}:
        raise HTTPException(status_code=403, detail="Account role is not permitted.")
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user.get("name", ""),
        "role": role,
    }


def require_auth(credentials: HTTPAuthorizationCredentials = Depends(AUTH_SCHEME)) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _authenticated_identity(credentials.credentials)["email"]


def require_admin(credentials: HTTPAuthorizationCredentials = Depends(AUTH_SCHEME)) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required.")
    identity = _authenticated_identity(credentials.credentials)
    if identity["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required.")
    return identity["email"]


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    return hash_password("PropIntel dummy authentication credential")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class PropertyInput(BaseModel):
    city: str
    locality: str
    property_type: str = Field(..., description="Apartment, Studio Apartment, or Villa")
    bhk: int = Field(..., ge=1, le=5)
    area_sqft: float = Field(..., gt=100)
    bedrooms: Optional[int] = Field(default=None, ge=1)
    bathrooms: Optional[int] = Field(default=None, ge=1)
    age_years: int = Field(default=0, ge=0)
    floor: int = Field(default=0, ge=0)
    total_floors: Optional[int] = Field(default=None, ge=1)
    furnishing: str = "Unfurnished"
    parking: int = Field(default=0, ge=0)
    amenities: List[str] = Field(default_factory=list)
    listed_price: Optional[float] = Field(default=None, ge=0)

    @field_validator("city", "locality")
    @classmethod
    def require_nonempty_location(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("City and locality must not be empty.")
        return normalized

    @field_validator("property_type")
    @classmethod
    def canonicalize_property_type(cls, value: str) -> str:
        normalized = normalize_property_type(value)
        if normalized is None:
            raise ValueError(
                "Property type must be Apartment, Studio Apartment, or Villa, as represented in training data."
            )
        return normalized

    @field_validator("furnishing")
    @classmethod
    def canonicalize_furnishing(cls, value: str) -> str:
        normalized = normalize_furnishing(value)
        if normalized is None:
            raise ValueError("Furnishing must be Unfurnished, Semi-Furnished, or Furnished.")
        return normalized

    @field_validator("amenities")
    @classmethod
    def validate_amenities(cls, values: List[str]) -> List[str]:
        supported = {amenity.casefold(): amenity for amenity in AMENITIES_POOL}
        normalized = []
        seen = set()
        for value in values:
            key = value.strip().casefold()
            if key not in supported:
                raise ValueError(f"Unsupported amenity: {value}")
            if key not in seen:
                normalized.append(supported[key])
                seen.add(key)
        return normalized

    @field_validator("area_sqft", "listed_price")
    @classmethod
    def require_finite_prices_and_areas(cls, value: Optional[float]) -> Optional[float]:
        if value is not None and not np.isfinite(value):
            raise ValueError("Area and listed price must be finite numbers.")
        return value

    @model_validator(mode="after")
    def validate_floor_and_bedroom_consistency(self) -> "PropertyInput":
        if self.total_floors is not None and self.floor > self.total_floors:
            raise ValueError("Floor cannot exceed the building's total floors.")
        if self.bedrooms is not None and self.bedrooms != self.bhk:
            raise ValueError("Bedroom count must match the selected BHK configuration.")
        return self

    def to_payload(self) -> dict:
        # Pydantic v2: use model_dump() instead of deprecated dict()
        p = self.model_dump()
        p["bedrooms"] = p["bedrooms"] if p["bedrooms"] is not None else p["bhk"]
        p["bathrooms"] = p["bathrooms"] if p["bathrooms"] is not None else max(1, round(p["bhk"] * 0.8))
        p["total_floors"] = p["total_floors"] if p["total_floors"] is not None else p["floor"] + 1
        p["amenities_count"] = len(p.get("amenities") or [])
        if p["listed_price"] == 0:
            p["listed_price"] = None
        return p


class WhatIfInput(BaseModel):
    base: PropertyInput
    changes: dict

    @model_validator(mode="after")
    def validate_changes(self) -> "WhatIfInput":
        allowed = set(PropertyInput.model_fields) | {"amenities_count"}
        unsupported = set(self.changes) - allowed
        if unsupported:
            raise ValueError(f"Unsupported what-if fields: {', '.join(sorted(unsupported))}.")

        updates = {
            key: value
            for key, value in self.changes.items()
            if key != "amenities_count"
        }
        PropertyInput.model_validate({**self.base.model_dump(), **updates})

        amenities_count = self.changes.get("amenities_count")
        if amenities_count is not None and (
            type(amenities_count) is not int or amenities_count < 0
        ):
            raise ValueError("Amenities count must be a non-negative whole number.")
        return self


class RecommendInput(BaseModel):
    city: Optional[str] = Field(default=None, max_length=100)
    bhk: Optional[int] = Field(default=None, ge=1, le=5)
    property_type: Optional[str] = None
    furnishing: Optional[str] = None
    budget_min: float = Field(default=0, ge=0, allow_inf_nan=False)
    budget_max: float = Field(default=100_000_000, ge=0, allow_inf_nan=False)
    top_n: int = Field(default=6, ge=1, le=50)

    @field_validator("city")
    @classmethod
    def normalize_city(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            return None
        return normalized

    @field_validator("property_type")
    @classmethod
    def normalize_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = normalize_property_type(value)
        if normalized is None:
            raise ValueError("Choose a property type represented in the training data.")
        return normalized

    @field_validator("furnishing")
    @classmethod
    def normalize_furnishing_value(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = normalize_furnishing(value)
        if normalized is None:
            raise ValueError("Furnishing must be Unfurnished, Semi-Furnished, or Furnished.")
        return normalized

    @model_validator(mode="after")
    def validate_budget_range(self) -> "RecommendInput":
        if self.budget_min > self.budget_max:
            raise ValueError("Minimum budget cannot exceed maximum budget.")
        return self


# ---------------------------------------------------------------------------
# Meta / config endpoints
# ---------------------------------------------------------------------------
@app.post("/api/auth/login")
def login(
    payload: LoginInput,
    request: Request = None,
    response: Response = None,
):
    if request is not None:
        _enforce_rate_limit(request, "login", payload.email, 10, 900, ip_max_attempts=30)
    if (
        AUTH_EMAIL is not None
        and AUTH_PASSWORD is not None
        and hmac.compare_digest(payload.email, AUTH_EMAIL)
        and hmac.compare_digest(payload.password, AUTH_PASSWORD)
    ):
        return _auth_response(
            response,
            f"admin:{AUTH_EMAIL}",
            AUTH_EMAIL,
            AUTH_EMAIL,
            "admin",
            payload.remember,
        )

    try:
        user = database.get_user(payload.email)
    except DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Authentication is temporarily unavailable."
        ) from exc
    valid_password = bool(
        (
            verify_password(payload.password, user.get("password_hash", ""))
            if user
            else verify_password(payload.password, _dummy_password_hash())
        )
    )
    if not valid_password:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if password_needs_rehash(user.get("password_hash", "")):
        try:
            database.update_password_hash(user["id"], hash_password(payload.password))
        except DatabaseUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Authentication is temporarily unavailable."
            ) from exc

    return _auth_response(
        response,
        user["id"],
        payload.email,
        user.get("name", ""),
        user.get("role", "user"),
        payload.remember,
    )


@app.post("/api/auth/register")
def register(payload: RegisterInput, request: Request, response: Response):
    _enforce_rate_limit(request, "register", payload.email, 3, 3600, ip_max_attempts=8)
    if AUTH_EMAIL and hmac.compare_digest(payload.email, AUTH_EMAIL):
        raise HTTPException(status_code=409, detail="This email address is reserved.")

    try:
        user_id = database.create_user(
            {
                "name": payload.name,
                "email": payload.email,
                "password_hash": hash_password(payload.password),
                "created_at": datetime.now(timezone.utc),
            }
        )
    except UserAlreadyExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Registration is temporarily unavailable."
        ) from exc

    result = _auth_response(
        response,
        user_id,
        payload.email,
        payload.name,
        "user",
        payload.remember,
    )
    result["message"] = "Account created successfully."
    return result


@app.get("/api/auth/csrf")
def get_csrf_token(request: Request):
    _require_trusted_origin(request)
    cookie_token = request.cookies.get(_refresh_cookie_name())
    if not cookie_token:
        raise HTTPException(status_code=401, detail="Authentication session is unavailable.")
    now = datetime.now(timezone.utc)
    try:
        session = database.get_active_refresh_session(_token_hash("refresh", cookie_token), now)
    except DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Authentication is temporarily unavailable."
        ) from exc
    if not session:
        raise HTTPException(status_code=401, detail="Authentication session is unavailable.")
    return {"csrf_token": _csrf_token(cookie_token)}


@app.post("/api/auth/refresh")
def refresh_session(request: Request, response: Response):
    refresh_token = request.cookies.get(_refresh_cookie_name())
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Authentication session is unavailable.")
    _require_csrf(request, refresh_token)
    now = datetime.now(timezone.utc)
    next_refresh = secrets.token_urlsafe(48)
    next_hash = _token_hash("refresh", next_refresh)
    next_session = {
        "_id": next_hash,
        "created_at": now,
        "expires_at": now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
    }
    try:
        state, previous = database.rotate_refresh_session(
            _token_hash("refresh", refresh_token), next_session, now
        )
    except DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Authentication is temporarily unavailable."
        ) from exc
    if state != "rotated" or previous is None:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Authentication session is invalid or expired.")

    user_id = previous["user_id"]
    if user_id.startswith("admin:"):
        email = user_id.removeprefix("admin:")
        if not AUTH_EMAIL or not hmac.compare_digest(email, AUTH_EMAIL):
            _clear_refresh_cookie(response)
            raise HTTPException(status_code=401, detail="Authentication session is invalid.")
        name, role = email, "admin"
    else:
        try:
            user = database.get_user_by_id(user_id)
        except DatabaseUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Authentication is temporarily unavailable."
            ) from exc
        if not user:
            _clear_refresh_cookie(response)
            raise HTTPException(status_code=401, detail="Authentication session is invalid.")
        email, name, role = user["email"], user.get("name", ""), user.get("role", "user")

    access_token = create_access_token(
        user_id,
        email,
        role,
        AUTH_SECRET.decode("utf-8"),
        secrets.token_urlsafe(18),
        int(now.timestamp()),
    )
    _set_refresh_cookie(response, next_refresh, previous.get("remember", True))
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "csrf_token": _csrf_token(next_refresh),
        "user": {"id": user_id, "email": email, "name": name, "role": role},
    }


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    refresh_token = request.cookies.get(_refresh_cookie_name())
    if refresh_token:
        _require_csrf(request, refresh_token)
        try:
            database.revoke_refresh_session(
                _token_hash("refresh", refresh_token), datetime.now(timezone.utc)
            )
        except DatabaseUnavailable as exc:
            raise HTTPException(
                status_code=503, detail="Logout is temporarily unavailable."
            ) from exc
    _clear_refresh_cookie(response)
    return {"ok": True}


@app.post("/api/auth/forgot-password")
def forgot_password(payload: EmailInput, request: Request):
    _enforce_rate_limit(request, "forgot-password-ip", "shared", 10, 3600)
    _enforce_rate_limit(request, "forgot-password-email", payload.email, 5, 3600)
    generic_response = {
        "message": "If an account exists and email delivery is configured, reset instructions will be sent."
    }
    if not email_delivery_configured():
        return {
            "message": (
                "Password reset email is unavailable. Configure SMTP_HOST, SMTP_PORT, "
                "and EMAIL_FROM, plus SMTP_USERNAME and SMTP_PASSWORD if required."
            )
        }
    try:
        user = database.get_user(payload.email)
        if not user:
            return generic_response
        token = secrets.token_urlsafe(40)
        token_hash = _token_hash("password-reset", token)
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=PASSWORD_RESET_EXPIRE_MINUTES
        )
        database.create_password_reset(token_hash, user["id"], expires_at)
        reset_url = f"{FRONTEND_BASE_URL}/reset-password?token={token}"
        send_email(
            user["email"],
            "Reset your PropIntel password",
            (
                f"Use this link to reset your PropIntel password:\n{reset_url}\n\n"
                f"The link expires in {PASSWORD_RESET_EXPIRE_MINUTES} minutes. "
                "If you did not request this, you can ignore this message."
            ),
        )
    except (DatabaseUnavailable, OSError, RuntimeError, ValueError):
        logger.warning("Password reset request could not be completed.")
    return generic_response


@app.post("/api/auth/reset-password")
def reset_password(payload: ResetPasswordInput, request: Request):
    _enforce_rate_limit(request, "reset-password-ip", "shared", 10, 3600)
    token_hash = _token_hash("password-reset", payload.token)
    try:
        user_id = database.consume_password_reset(
            token_hash,
            hash_password(payload.new_password),
            datetime.now(timezone.utc),
        )
        if not user_id:
            raise HTTPException(status_code=400, detail="The reset link is invalid or expired.")
    except DatabaseUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Password reset is temporarily unavailable."
        ) from exc
    return {"message": "Password reset complete. Sign in with your new password."}


@app.get("/api/meta")
def get_meta():
    _require_ready()
    df = STATE["catalog"]
    prices = df["price_per_sqft"].replace([np.inf, -np.inf], np.nan).dropna()
    listed_prices = pd.to_numeric(df["listed_price"], errors="coerce").dropna()
    localities_by_city = {
        str(city).strip(): sorted(
            {str(locality).strip() for locality in group["locality"].dropna() if str(locality).strip()},
            key=str.casefold,
        )
        for city, group in df.groupby("city", sort=True)
    }
    return {
        "cities": sorted(df["city"].dropna().unique().tolist()),
        "localities": sorted(df["locality"].dropna().unique().tolist()),
        "localities_by_city": localities_by_city,
        "property_types": sorted(df["property_type"].dropna().unique().tolist()),
        "furnishing_options": ["Unfurnished", "Semi-Furnished", "Furnished"],
        "amenities": AMENITIES_POOL,
        "stats": {
            "total_properties": int(len(df)),
            "cities_covered": int(df["city"].nunique()),
            "avg_price_per_sqft": round(float(prices.mean()), 0) if not prices.empty else 0,
            "max_listed_price": float(listed_prices.max()) if not listed_prices.empty else 0,
        },
        "model_metrics": STATE["predictor"].metrics,
    }


# ---------------------------------------------------------------------------
# GET /api/listings
# ---------------------------------------------------------------------------
@app.get("/api/listings")
def get_listings(
    _: str = Depends(require_auth),
    locality: Optional[str] = Query(default=None, min_length=1, max_length=200),
    property_type: Optional[str] = Query(default=None, min_length=1, max_length=100),
    bhk: Optional[int] = Query(default=None, ge=1, le=8),
    budget_max: Optional[float] = Query(default=None, ge=0, allow_inf_nan=False),
    area_min: float = Query(default=0, ge=0, allow_inf_nan=False),
    search: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=24, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    _require_ready()
    df = STATE["catalog"].copy()

    def normalized(value: object) -> str:
        return " ".join(str(value).strip().casefold().split())

    if locality:
        wanted_locality = normalized(locality)
        df = df.loc[df["locality"].map(normalized) == wanted_locality]
    if property_type:
        wanted_type = normalized(property_type)
        df = df.loc[df["property_type"].map(normalized) == wanted_type]
    if bhk is not None:
        df = df.loc[pd.to_numeric(df["bhk"], errors="coerce") == bhk]

    prices = pd.to_numeric(df["listed_price"], errors="coerce")
    areas = pd.to_numeric(df["area_sqft"], errors="coerce")
    df = df.loc[prices.notna() & areas.notna() & areas.ge(area_min)]
    if budget_max is not None:
        df = df.loc[pd.to_numeric(df["listed_price"], errors="coerce").le(budget_max)]

    if search and search.strip():
        query = normalized(search)
        searchable = (
            df["locality"].map(normalized)
            + " "
            + df["city"].map(normalized)
            + " "
            + df["property_type"].map(normalized)
        )
        df = df.loc[searchable.str.contains(query, regex=False)]

    count = len(df)
    page = df.iloc[offset : offset + limit]
    results = [
        {
            "id": str(row["id"]),
            "city": str(row["city"]),
            "locality": str(row["locality"]),
            "property_type": str(row["property_type"]),
            "bhk": int(row["bhk"]),
            "area_sqft": float(row["area_sqft"]),
            "listed_price": float(row["listed_price"]),
            "furnishing": str(row["furnishing"]),
        }
        for _, row in page.iterrows()
    ]
    return {"count": count, "limit": limit, "offset": offset, "results": results}


# ---------------------------------------------------------------------------
# POST /api/predict
# ---------------------------------------------------------------------------
def calculate_prediction(payload: PropertyInput) -> dict:
    _require_ready()
    p = payload.to_payload()
    catalog = STATE["catalog"]
    normalize = lambda value: " ".join(str(value).strip().casefold().split())  # noqa: E731
    cities_by_normalized_name = {
        normalize(city): str(city).strip() for city in catalog["city"].dropna().unique()
    }
    canonical_city = cities_by_normalized_name.get(normalize(payload.city))
    if canonical_city is None:
        raise HTTPException(
            status_code=422,
            detail="The selected market zone is not in the property catalog.",
        )

    localities_by_normalized_name = {
        normalize(locality): str(locality).strip()
        for locality in catalog.loc[catalog["city"] == canonical_city, "locality"].dropna().unique()
    }
    canonical_locality = localities_by_normalized_name.get(normalize(payload.locality))
    if canonical_locality is None:
        raise HTTPException(
            status_code=422,
            detail="The selected locality does not belong to the selected market zone.",
        )

    p["city"] = canonical_city
    p["locality"] = canonical_locality
    predictor: PropIntelPredictor = STATE["predictor"]
    explainer: XAIExplainer = STATE["explainer"]

    try:
        result = predictor.predict(p)
        explanation = explainer.explain(p, top_k=7)
    except Exception:  # noqa: BLE001
        logger.exception("Prediction calculation failed.")
        raise HTTPException(
            status_code=500,
            detail="Prediction could not be calculated due to an internal error.",
        ) from None

    return {"prediction": result, "explanation": explanation, "input": p}


@app.post("/api/predict")
def predict(payload: PropertyInput, _: str = Depends(require_auth)):
    return calculate_prediction(payload)


@app.post("/api/prediction-history")
def save_prediction_history(payload: PropertyInput, user_email: str = Depends(require_auth)):
    result = calculate_prediction(payload)
    document = {
        "user_email": user_email,
        "input": result["input"],
        "prediction": result["prediction"],
        "explanation": result["explanation"],
        "created_at": datetime.now(timezone.utc),
    }
    try:
        record_id = database.save_prediction(document)
    except DatabaseUnavailable as exc:
        logger.warning("Prediction-history save failed: MongoDB unavailable.")
        raise HTTPException(
            status_code=503,
            detail=f"Prediction history could not be saved. {exc}",
        )
    return {
        "id": record_id,
        "created_at": document["created_at"].isoformat(),
        "prediction": result["prediction"],
        "explanation": result["explanation"],
        "input": result["input"],
    }


@app.get("/api/prediction-history")
def get_prediction_history(
    user_email: str = Depends(require_auth),
    limit: int = Query(default=20, ge=1, le=100),
):
    try:
        results = database.get_predictions(user_email, limit)
    except DatabaseUnavailable as exc:
        logger.warning("Prediction-history read failed: MongoDB unavailable.")
        raise HTTPException(
            status_code=503,
            detail=f"Prediction history is unavailable. {exc}",
        )
    return {"count": len(results), "results": results}


@app.get("/api/health")
def health():
    database_status = database.health_status()
    database_health = {"status": database_status}
    if database_status != "connected":
        database_health["diagnostic"] = database.diagnostic
    return {
        "status": "ok" if STATE.get("ready") and database_status == "connected" else "degraded",
        "ml_engine": "ready" if STATE.get("ready") else "unavailable",
        "database": database_health,
    }


# ---------------------------------------------------------------------------
# POST /api/what-if
# ---------------------------------------------------------------------------
@app.post("/api/what-if")
def what_if(payload: WhatIfInput, _: str = Depends(require_auth)):
    _require_ready()
    engine: WhatIfEngine = STATE["what_if"]
    base_payload = payload.base.to_payload()
    updates = {
        key: value
        for key, value in payload.changes.items()
        if key != "amenities_count"
    }
    if updates:
        normalized = PropertyInput.model_validate(
            {**payload.base.model_dump(), **updates}
        ).to_payload()
        changes = {key: normalized[key] for key in updates}
    else:
        changes = {}
    if "amenities_count" in payload.changes:
        changes["amenities_count"] = payload.changes["amenities_count"]
    try:
        result = engine.evaluate(base_payload, changes)
    except Exception:  # noqa: BLE001
        logger.exception("What-if calculation failed.")
        raise HTTPException(
            status_code=500,
            detail="What-if analysis could not be calculated due to an internal error.",
        ) from None
    return result


# ---------------------------------------------------------------------------
# GET /api/compare
# ---------------------------------------------------------------------------
@app.get("/api/compare")
def compare(
    _: str = Depends(require_auth),
    city: Optional[str] = Query(default=None, min_length=1, max_length=100),
    bhk: Optional[int] = Query(default=None, ge=1, le=5),
    budget_min: float = Query(default=0, ge=0, allow_inf_nan=False),
    budget_max: float = Query(default=100_000_000, ge=0, allow_inf_nan=False),
    limit: int = Query(default=20, ge=1, le=100),
):
    _require_ready()
    df = STATE["catalog"].copy()
    predictor: PropIntelPredictor = STATE["predictor"]

    if city:
        normalized_city = " ".join(city.strip().casefold().split())
        city_lookup = {
            " ".join(str(value).strip().casefold().split()): str(value)
            for value in df["city"].dropna().unique()
        }
        canonical_city = city_lookup.get(normalized_city)
        if canonical_city is None:
            raise HTTPException(status_code=422, detail="The selected market zone is not in the property catalog.")
        df = df[df["city"] == canonical_city]
    if bhk:
        df = df[df["bhk"] == bhk]
    if budget_min < 0 or budget_max < 0 or budget_min > budget_max:
        raise HTTPException(status_code=422, detail="Budget must be non-negative and minimum cannot exceed maximum.")
    df = filter_properties_by_budget(df, budget_min, budget_max)
    df = df.head(limit)

    rows = []
    prediction_payloads = []
    for _, r in df.iterrows():
        payload = {
            "city": r["city"], "locality": r["locality"], "property_type": r["property_type"],
            "bhk": int(r["bhk"]), "area_sqft": r["area_sqft"], "bedrooms": r["bedrooms"],
            "bathrooms": r["bathrooms"], "age_years": r["age_years"], "floor": r["floor"],
            "total_floors": r["total_floors"], "furnishing": r["furnishing"], "parking": r["parking"],
            "amenities_count": r["amenities_count"],
        }
        prediction_payloads.append(payload)
        rows.append(r)

    estimates = predictor.predict_many(prediction_payloads)
    results = []
    for r, payload, ai_estimate in zip(rows, prediction_payloads, estimates):
        variance = variance_percentage(r["listed_price"], ai_estimate)
        reliability = predictor.assess_reliability(payload)
        results.append(
            {
                "id": r["id"], "city": r["city"], "locality": r["locality"],
                "property_type": r["property_type"], "bhk": int(r["bhk"]),
                "area_sqft": r["area_sqft"], "listed_price": r["listed_price"],
                "ai_estimate": round(ai_estimate, 0), "variance_pct": round(variance, 1),
                "furnishing": r["furnishing"], "amenities": r["amenities"],
                **reliability,
            }
        )

    # Sort by best value first: most undervalued (negative variance) first
    results.sort(key=lambda x: x["variance_pct"])
    return {"count": len(results), "results": results}


# ---------------------------------------------------------------------------
# POST /api/recommend
# ---------------------------------------------------------------------------
@app.post("/api/recommend")
def recommend(payload: RecommendInput, _: str = Depends(require_auth)):
    _require_ready()
    engine: RecommendationEngine = STATE["recommender"]
    # Pydantic v2: use model_dump() instead of deprecated dict()
    prefs = payload.model_dump()
    top_n = prefs.pop("top_n", 6)
    if prefs["city"]:
        city_lookup = {
            " ".join(str(value).strip().casefold().split()): str(value)
            for value in STATE["catalog"]["city"].dropna().unique()
        }
        canonical_city = city_lookup.get(" ".join(prefs["city"].casefold().split()))
        if canonical_city is None:
            raise HTTPException(status_code=422, detail="The selected market zone is not in the property catalog.")
        prefs["city"] = canonical_city
    available_types = set(STATE["catalog"]["property_type"].dropna().unique())
    if prefs["property_type"] and prefs["property_type"] not in available_types:
        raise HTTPException(status_code=422, detail="The selected property type is not in the property catalog.")
    results, matching_count = engine.recommend_with_count(prefs, top_n=top_n)
    return {"count": matching_count, "results": results}


# ---------------------------------------------------------------------------
# GET /api/market-trends
# ---------------------------------------------------------------------------
@app.get("/api/market-trends")
def market_trends(city: Optional[str] = Query(default=None, min_length=1, max_length=100)):
    _require_ready()
    df = STATE["catalog"].copy()
    if city:
        normalized_city = " ".join(city.strip().casefold().split())
        city_lookup = {
            " ".join(str(value).strip().casefold().split()): str(value)
            for value in df["city"].dropna().unique()
        }
        canonical_city = city_lookup.get(normalized_city)
        if canonical_city is None:
            raise HTTPException(status_code=422, detail="The selected market zone is not in the property catalog.")
        df = df[df["city"] == canonical_city]

    by_city = (
        df.groupby("city")["price_per_sqft"]
        .mean()
        .round(0)
        .sort_values(ascending=False)
        .to_dict()
    )
    bhk_distribution = df["bhk"].value_counts().sort_index().to_dict()
    prices_per_sqft = df["price_per_sqft"].replace([np.inf, -np.inf], np.nan).dropna()

    return {
        "avg_price_per_sqft_by_city": by_city,
        "average_price_per_sqft": round(float(prices_per_sqft.mean()), 0) if not prices_per_sqft.empty else 0,
        "bhk_distribution": {str(k): int(v) for k, v in bhk_distribution.items()},
        "forecast": {},
        "total_properties": int(len(df)),
    }


@app.get("/")
def root():
    return {
        "service": "PropIntel API",
        "status": "ok" if STATE.get("ready") else "degraded",
        "docs": "/docs",
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0" if IS_PRODUCTION else "127.0.0.1",
        port=int(os.getenv("PORT", "8000")),
    )
