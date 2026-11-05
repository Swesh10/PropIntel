"""
PropIntel :: ml_engine.py
-------------------------------------------------
Core ML + XAI + decision-support engine.

Classes
-------
PropIntelPredictor   - preprocessing pipeline + gradient-boosted regressor
XAIExplainer          - INR-domain Permutation SHAP -> local feature attributions
WhatIfEngine          - deterministic re-inference over a modified feature set
RecommendationEngine  - value-for-money + budget-fit scoring over the catalog
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
import threading
from pathlib import Path

logger = logging.getLogger("propintel.ml")
_SHAP_RANDOM_LOCK = threading.Lock()

import numpy as np
import pandas as pd
import shap
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBRegressor

from data_gen import AMENITIES_POOL, CITIES, FURNISHING, LOCALITIES, PROPERTY_TYPES

NUMERIC_FEATURES = [
    "bhk",
    "area_sqft",
    "age_years",
    "floor",
    "total_floors",
    "amenities_count",
]
CATEGORICAL_FEATURES = ["city", "locality", "property_type", "furnishing"]
ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

FEATURE_DISPLAY_NAMES = {
    "bhk": "BHK Configuration",
    "area_sqft": "Area (sq.ft)",
    "bedrooms": "Bedrooms",
    "bathrooms": "Bathrooms",
    "age_years": "Property Age",
    "floor": "Floor Level",
    "total_floors": "Building Height",
    "parking": "Parking Slots",
    "amenities_count": "Amenities",
    "city": "City",
    "locality": "Locality",
    "property_type": "Property Type",
    "furnishing": "Furnishing",
}


def normalize_property_type(value: str) -> str | None:
    if pd.isna(value):
        return None
    raw = str(value).strip().lower()
    mapping = {
        "residential apartment": "Apartment",
        "studio apartment": "Studio Apartment",
        "apartment": "Apartment",
        "independent house": "Villa",
        "independent house/villa": "Villa",
        "villa": "Villa",
    }
    return mapping.get(raw)


def normalize_furnishing(value: str) -> str | None:
    if pd.isna(value):
        return None
    val = str(value).strip().lower()
    if val in {"0", "unfurnished", "not furnished"}:
        return "Unfurnished"
    if val in {"1", "semi-furnished", "semi furnished", "semi"}:
        return "Semi-Furnished"
    if val in {"2", "4", "furnished", "fully furnished", "full furnished"}:
        return "Furnished"
    return None


def _format_inr(value: float) -> str:
    return f"₹{value:,.0f}"


def build_preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), NUMERIC_FEATURES),
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                CATEGORICAL_FEATURES,
            ),
        ]
    )


def build_training_profile(df: pd.DataFrame) -> dict:
    numeric_ranges = {
        feature: [
            float(df[feature].quantile(0.01)),
            float(df[feature].quantile(0.99)),
        ]
        for feature in NUMERIC_FEATURES
    }
    categories = {
        feature: sorted(df[feature].dropna().astype(str).unique().tolist())
        for feature in CATEGORICAL_FEATURES
    }
    category_counts = {
        feature: {
            str(category): int(count)
            for category, count in df[feature].value_counts().items()
        }
        for feature in CATEGORICAL_FEATURES
    }
    numeric_medians = {
        feature: float(df[feature].median())
        for feature in NUMERIC_FEATURES
    }
    locality_counts = {}
    for (city, locality), count in df.groupby(["city", "locality"]).size().items():
        locality_counts.setdefault(str(city), {})[str(locality)] = int(count)
    return {
        "numeric_ranges": numeric_ranges,
        "numeric_medians": numeric_medians,
        "categories": categories,
        "category_counts": category_counts,
        "locality_counts": locality_counts,
        "minimum_locality_samples": 10,
        "minimum_property_type_samples": 50,
    }


def cross_validated_catalog_estimates(
    predictor: "PropIntelPredictor", df: pd.DataFrame, n_splits: int = 5
) -> np.ndarray:
    """Estimate catalog rows with folds that exclude each row from model fitting."""
    if not predictor.is_fitted or predictor.pipeline is None:
        raise RuntimeError("Cross-validated catalog estimates require a fitted model pipeline.")
    if predictor.target_representation not in {"total_price", "price_per_sqft"}:
        raise ValueError("Unsupported model target representation.")

    features = df[ALL_FEATURES]
    target_column = (
        "fair_price"
        if predictor.target_representation == "total_price"
        else "price_per_sqft"
    )
    target = pd.to_numeric(df[target_column], errors="raise").to_numpy(dtype=float)
    groups = pd.util.hash_pandas_object(features, index=False).to_numpy()
    fold_count = min(n_splits, pd.Series(groups).nunique())
    if fold_count < 2:
        raise ValueError("At least two distinct property feature groups are required.")

    estimates = np.full(len(df), np.nan, dtype=float)
    splitter = GroupKFold(n_splits=fold_count)
    for training_indices, validation_indices in splitter.split(
        features, target, groups=groups
    ):
        fold_pipeline = clone(predictor.pipeline)
        fold_target = target[training_indices]
        if predictor._use_log_target:
            fold_target = np.log1p(fold_target)
        fold_pipeline.fit(features.iloc[training_indices], fold_target)
        fold_predictions = np.asarray(
            fold_pipeline.predict(features.iloc[validation_indices]), dtype=float
        )
        if predictor._use_log_target:
            fold_predictions = np.expm1(fold_predictions)
        fold_predictions = np.maximum(fold_predictions, 1.0)
        if predictor.target_representation == "price_per_sqft":
            fold_predictions *= df.iloc[validation_indices]["area_sqft"].to_numpy(dtype=float)
        estimates[validation_indices] = fold_predictions

    if not np.isfinite(estimates).all():
        raise RuntimeError("Cross-validated catalog estimates contain invalid values.")
    return estimates


def variance_percentage(listed_price: float, estimated_price: float) -> float:
    if estimated_price <= 0:
        raise ValueError("Estimated price must be greater than zero.")
    return (listed_price - estimated_price) / estimated_price * 100


def is_within_budget(price: float, budget_min: float, budget_max: float) -> bool:
    if budget_min < 0 or budget_max < 0 or budget_min > budget_max:
        raise ValueError("Budget minimum must be non-negative and no greater than budget maximum.")
    return budget_min <= price <= budget_max


def filter_properties_by_budget(
    properties: pd.DataFrame, budget_min: float, budget_max: float
) -> pd.DataFrame:
    if budget_min < 0 or budget_max < 0 or budget_min > budget_max:
        raise ValueError("Budget minimum must be non-negative and no greater than maximum budget.")
    prices = pd.to_numeric(properties["listed_price"], errors="coerce")
    return properties.loc[prices.between(budget_min, budget_max, inclusive="both")].copy()


def _parse_price_to_inr(value):
    if pd.isna(value):
        return np.nan
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none"}:
        return np.nan
    s = s.replace("₹", "").replace("Rs", "").replace("INR", "")
    s = s.replace(",", "")
    low = s.lower()
    if "/" in low and any(token in low for token in ["bed", "bedroom", "bhk"]):
        return np.nan
    matches = list(
        re.finditer(
            r"(\d+(?:\.\d+)?)(?:\s*(crores?|cr|lakhs?|lacs?|lac|l|k)\b)?",
            low,
        )
    )
    if not matches:
        return np.nan

    units = [match.group(2) for match in matches]
    explicit_units = [(index, unit) for index, unit in enumerate(units) if unit]
    for index, unit in enumerate(units):
        if unit is None and explicit_units:
            units[index] = min(explicit_units, key=lambda item: abs(item[0] - index))[1]

    multipliers = {
        "cr": 10_000_000,
        "crore": 10_000_000,
        "crores": 10_000_000,
        "lac": 100_000,
        "lacs": 100_000,
        "lakh": 100_000,
        "lakhs": 100_000,
        "l": 100_000,
        "k": 1_000,
    }
    amounts = [
        float(match.group(1)) * multipliers.get(unit, 1)
        for match, unit in zip(matches, units)
    ]
    return min(amounts)


def _parse_area_sqft(value):
    if pd.isna(value):
        return np.nan
    s = str(value).strip().lower()
    if not s or s == "nan":
        return np.nan
    matches = re.findall(r"\d+(?:\.\d+)?", s)
    if not matches:
        return np.nan
    return float(matches[0])


def _parse_locality(value, city_name: str = "") -> str:
    if pd.isna(value):
        return str(city_name).strip()
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return str(city_name).strip()
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        parsed = None
    if isinstance(parsed, dict):
        locality = parsed.get("LOCALITY_NAME") or parsed.get("locality") or parsed.get("locality_name")
        if locality:
            return str(locality).strip()
    match = re.search(r"LOCALITY_NAME': '([^']+)'", text)
    if match:
        return match.group(1).strip()
    return text.strip() or str(city_name).strip()


def _normalize_city(value: str) -> str:
    city = str(value).strip()
    if not city or city.lower() == "nan":
        return "Unknown"
    return city.replace("  ", " ").strip()


def prepare_mumbai_dataset(csv_path: str | Path = Path(__file__).resolve().parents[1] / "dataset" / "mumbai.csv") -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    before = len(df)

    sale_df = df[df["PREFERENCE"].fillna("").astype(str).str.strip().str.upper() == "S"].copy()
    sale_df = sale_df[~sale_df["PRICE"].astype(str).str.contains("/", na=False)]
    sale_df = sale_df[~sale_df["PRICE"].astype(str).str.lower().str.contains("bedroom|bed|month|rent|per", na=False)]

    sale_df["price_inr"] = sale_df["PRICE"].map(_parse_price_to_inr)
    sale_df["source_verified"] = (
        sale_df["VERIFIED"].fillna("").astype(str).str.strip().str.upper().eq("Y")
    )
    sale_df["area_sqft"] = sale_df["AREA"].map(_parse_area_sqft)
    sale_df["city"] = sale_df["CITY"].map(_normalize_city)
    sale_df["locality"] = sale_df.apply(lambda row: _parse_locality(row["location"], row["CITY"]), axis=1)
    sale_df["property_type"] = sale_df["PROPERTY_TYPE"].map(normalize_property_type)
    unsupported_property_type_rows = int(sale_df["property_type"].isna().sum())
    sale_df["bhk"] = pd.to_numeric(sale_df["BEDROOM_NUM"], errors="coerce").fillna(1).round().astype(int)
    sale_df["bedrooms"] = sale_df["bhk"].copy()
    sale_df["bathrooms"] = sale_df["bhk"].clip(lower=1).apply(lambda x: max(1, round(x * 0.8)))
    sale_df["age_years"] = pd.to_numeric(sale_df["AGE"], errors="coerce").fillna(0).clip(lower=0)
    sale_df["floor"] = pd.to_numeric(sale_df["FLOOR_NUM"], errors="coerce").fillna(0).clip(lower=0)
    sale_df["total_floors"] = pd.to_numeric(sale_df["TOTAL_FLOOR"], errors="coerce").fillna(sale_df["floor"] + 1).clip(lower=1)
    sale_df["furnishing"] = sale_df["FURNISH"].map(normalize_furnishing)
    sale_df["parking"] = 0
    sale_df["amenities_count"] = sale_df["AMENITIES"].fillna("").astype(str).str.split(",").apply(lambda xs: len([x for x in xs if x and str(x).strip()]))
    sale_df["amenities"] = sale_df["AMENITIES"].fillna("").astype(str).replace("nan", "")
    sale_df["listed_price"] = sale_df["price_inr"]
    sale_df["fair_price"] = sale_df["price_inr"]
    sale_df["price_per_sqft"] = (sale_df["price_inr"] / sale_df["area_sqft"]).replace([np.inf, -np.inf], np.nan)
    sale_df["id"] = sale_df["PROP_ID"].fillna(pd.Series(np.arange(len(sale_df)), index=sale_df.index).astype(str))

    clean = sale_df[
        [
            "id", "city", "locality", "property_type", "bhk", "area_sqft", "source_verified", "bedrooms",
                "bathrooms", "age_years", "floor", "total_floors", "furnishing", "parking",
                "amenities_count", "amenities", "fair_price", "listed_price", "price_per_sqft"
        ]
    ].copy()
    clean = clean.dropna(
        subset=[
            "city",
            "locality",
            "property_type",
            "fair_price",
            "area_sqft",
            "price_per_sqft",
            "furnishing",
            *ALL_FEATURES,
        ]
    )

    # -----------------------------------------------------------------------
    # Keep the existing, documented price-per-area bounds, absolute price cap,
    # and area-tail trimming policy. Track each filter separately so the
    # training log does not attribute every removed row to a PSF outlier.
    PSF_MIN = 3_000    # below this is obviously wrong for any Mumbai property
    PSF_MAX = 80_000   # above this is a data-entry error for all practical purposes
    PRICE_MAX = 200_000_000  # hard cap at ₹20 Cr — removes duplicate erroneous rows

    before_outlier_filters = len(clean)
    clean = clean[(clean["price_per_sqft"] >= PSF_MIN) & (clean["price_per_sqft"] <= PSF_MAX)]
    after_psf_filter = len(clean)
    clean = clean[clean["listed_price"] <= PRICE_MAX]
    after_price_filter = len(clean)
    clean = clean[(clean["area_sqft"] >= clean["area_sqft"].quantile(0.01)) & (clean["area_sqft"] <= clean["area_sqft"].quantile(0.99))]
    after_area_filter = len(clean)
    clean = clean.reset_index(drop=True)
    print(
        f"Mumbai dataset: {before} rows -> {before_outlier_filters} valid sale/type/features "
        f"-> {len(clean)} rows after outlier filters "
        f"(unsupported property types encountered: {unsupported_property_type_rows}; "
        f"PSF exclusions: {before_outlier_filters - after_psf_filter}; "
        f"price-cap exclusions: {after_psf_filter - after_price_filter}; "
        f"area-tail exclusions: {after_price_filter - after_area_filter})"
    )
    return clean


# ---------------------------------------------------------------------------
# 1. PropIntelPredictor
# ---------------------------------------------------------------------------
class PropIntelPredictor:
    """
    Preprocessing pipeline (OneHotEncoder + StandardScaler) feeding an
    ensemble regressor that predicts the cleaned listing-price target in INR.
    """

    def __init__(self, model_type: str = "xgboost"):
        self.model_type = model_type
        self.preprocessor: ColumnTransformer | None = None
        self.model = None
        self.pipeline: Pipeline | None = None
        self.metrics: dict = {}
        self.training_profile: dict = {}
        self.target_representation = "total_price"
        self.is_fitted = False

    # -- pipeline construction ------------------------------------------------
    def _build_preprocessor(self) -> ColumnTransformer:
        return build_preprocessor()

    def _build_model(self):
        if self.model_type == "xgboost":
            return XGBRegressor(
                n_estimators=350,
                max_depth=6,
                learning_rate=0.05,
                subsample=0.85,
                colsample_bytree=0.85,
                reg_lambda=1.0,
                random_state=42,
                n_jobs=-1,
            )
        if self.model_type == "random_forest":
            return RandomForestRegressor(
                n_estimators=400, max_depth=14, random_state=42, n_jobs=-1
            )
        if self.model_type == "gradient_boosting":
            return GradientBoostingRegressor(random_state=42)
        if self.model_type == "linear_regression":
            return LinearRegression()
        return RandomForestRegressor(
            n_estimators=400, max_depth=14, random_state=42, n_jobs=-1
        )

    # -- training ---------------------------------------------------------
    def fit(self, df: pd.DataFrame, target_col: str = "fair_price"):
        X = df[ALL_FEATURES].copy()
        y = df[target_col].copy()

        # -------------------------------------------------------------------
        # This training helper uses log1p; inference applies the matching inverse
        # transform. Persisted models store their own explicit transform setting.
        # -------------------------------------------------------------------
        self._use_log_target = True
        X_train, X_test, y_train_raw, y_test_raw = train_test_split(
            X, y, test_size=0.2, random_state=42
        )
        y_train = np.log1p(y_train_raw)

        self.training_profile = build_training_profile(df)
        self.preprocessor = self._build_preprocessor()
        Xt_train = self.preprocessor.fit_transform(X_train)
        Xt_test = self.preprocessor.transform(X_test)

        self.model = self._build_model()
        self.model.fit(Xt_train, y_train)

        preds_log = self.model.predict(Xt_test)
        preds = np.expm1(preds_log)  # inverse transform for metric reporting
        self.metrics = {
            "mae": float(mean_absolute_error(y_test_raw, preds)),
            "rmse": float(np.sqrt(mean_squared_error(y_test_raw, preds))),
            "r2": float(r2_score(y_test_raw, preds)),
            "mape": float(np.mean(np.abs((y_test_raw - preds) / y_test_raw)) * 100),
        }
        self.is_fitted = True
        return self

    # -- inference ----------------------------------------------------------
    def _row_from_payload(self, payload: dict) -> pd.DataFrame:
        row = {f: payload.get(f) for f in ALL_FEATURES}
        return pd.DataFrame([row])

    def predict(self, payload: dict) -> dict:
        if not self.is_fitted:
            raise RuntimeError("Model not fitted. Call fit() first.")
        price = max(self.predict_many([payload])[0], 1.0)
        psf = price / max(payload.get("area_sqft", 1), 1)

        listed_price = payload.get("listed_price")
        if listed_price is not None and float(listed_price) <= 0:
            listed_price = None
        delta_pct = None
        verdict = None
        if listed_price is not None:
            delta_pct = variance_percentage(listed_price, price)
            if delta_pct > 5:
                verdict = "Listed Above Estimate"
            elif delta_pct < -5:
                verdict = "Listed Below Estimate"
            else:
                verdict = "Near Estimate"

        reliability = self.assess_reliability(payload)
        limitations = [
            "Bathroom count is not available in the training data and did not affect this estimate."
        ]
        if int(payload.get("parking") or 0) > 0:
            limitations.append(
                "Parking is not available as a model feature, so the estimate does not account for parking spaces."
            )

        return {
            "predicted_price": round(price, 0),
            "predicted_price_per_sqft": round(psf, 0),
            "listed_price": listed_price,
            "delta_pct": round(delta_pct, 1) if delta_pct is not None else None,
            "verdict": verdict,
            "confidence_score": None,
            "limitations": limitations,
            **reliability,
        }

    def predict_many(self, payloads: list[dict]) -> list[float]:
        if not self.is_fitted:
            raise RuntimeError("Model not fitted. Call fit() first.")
        if not payloads:
            return []
        rows = [{feature: payload.get(feature) for feature in ALL_FEATURES} for payload in payloads]
        X = pd.DataFrame(rows, columns=ALL_FEATURES)
        Xt = self.preprocessor.transform(X)
        raw_preds = self.model.predict(Xt)
        # Inverse-transform if trained on log1p prices
        if getattr(self, "_use_log_target", False):
            prices = np.maximum(np.expm1(raw_preds), 1.0)
        else:
            prices = np.maximum(raw_preds, 1.0)
        if self.target_representation == "price_per_sqft":
            areas = np.asarray([float(payload["area_sqft"]) for payload in payloads])
            prices = prices * areas
        return [float(p) for p in prices]

    def assess_reliability(self, payload: dict) -> dict:
        profile = self.training_profile
        if not profile:
            return {
                "is_reliable": False,
                "reliability_warnings": ["Training-data profile is unavailable."],
            }

        warnings = []
        for feature, bounds in profile["numeric_ranges"].items():
            value = payload.get(feature)
            if value is None or not np.isfinite(float(value)):
                warnings.append(f"{FEATURE_DISPLAY_NAMES.get(feature, feature)} is missing or invalid.")
                continue
            lower, upper = bounds
            if value < lower or value > upper:
                warnings.append(
                    f"{FEATURE_DISPLAY_NAMES.get(feature, feature)} is outside the ranges "
                    "commonly seen in the training data."
                )

        for feature, known_values in profile["categories"].items():
            if feature == "locality":
                continue
            value = str(payload.get(feature, ""))
            if value not in known_values:
                warnings.append(f"{FEATURE_DISPLAY_NAMES.get(feature, feature)} is not represented in training data.")
                continue
            category_count = profile.get("category_counts", {}).get(feature, {}).get(value)
            minimum_category_samples = (
                profile["minimum_property_type_samples"]
                if feature == "property_type"
                else profile["minimum_locality_samples"]
            )
            if category_count is not None and category_count < minimum_category_samples:
                warnings.append(
                    f"{FEATURE_DISPLAY_NAMES.get(feature, feature)} ({value}) has limited "
                    f"examples in the training data ({category_count} listings)."
                )

        if int(payload.get("parking") or 0) > 0:
            warnings.append(
                "Parking details are not represented in the training data, so their effect cannot be assessed."
            )

        city = str(payload.get("city", ""))
        locality = str(payload.get("locality", ""))
        locality_count = profile["locality_counts"].get(city, {}).get(locality, 0)
        if locality_count < profile["minimum_locality_samples"]:
            warnings.append(
                f"Only {locality_count} training listings support this locality "
                f"(minimum {profile['minimum_locality_samples']})."
            )

        return {"is_reliable": not warnings, "reliability_warnings": warnings}

    def transform(self, payload: dict) -> np.ndarray:
        X = self._row_from_payload(payload)
        return self.preprocessor.transform(X)

    def get_feature_names(self) -> list:
        cat_encoder: OneHotEncoder = self.preprocessor.named_transformers_["cat"]
        cat_names = list(cat_encoder.get_feature_names_out(CATEGORICAL_FEATURES))
        return NUMERIC_FEATURES + cat_names


# ---------------------------------------------------------------------------
# 2. XAIExplainer
# ---------------------------------------------------------------------------
class XAIExplainer:
    """Permutation SHAP explanations for the complete INR prediction function."""

    PERMUTATIONS = 64
    BACKGROUND_ROWS = 32

    def __init__(self, predictor: PropIntelPredictor, background: pd.DataFrame):
        self.predictor = predictor
        if not predictor.is_fitted:
            raise RuntimeError("Cannot explain predictions before the model is fitted.")
        if not set(ALL_FEATURES).issubset(background.columns):
            raise ValueError("SHAP background data must contain every model input feature.")

        self._category_levels = {
            feature: [
                str(value)
                for value in categories
            ]
            for feature, categories in zip(
                CATEGORICAL_FEATURES,
                predictor.preprocessor.named_transformers_["cat"].categories_,
            )
        }
        self._category_codes = {
            feature: {value: index for index, value in enumerate(levels)}
            for feature, levels in self._category_levels.items()
        }
        sample = background[ALL_FEATURES].sample(
            n=min(self.BACKGROUND_ROWS, len(background)),
            random_state=42,
        )
        self._background = self._encode_frame(sample)
        self.explainer = shap.PermutationExplainer(
            self._predict_prices,
            self._background,
            feature_names=ALL_FEATURES,
            seed=42,
        )
        self._max_evals = (2 * len(ALL_FEATURES) + 1) * self.PERMUTATIONS

    def _encode_frame(self, frame: pd.DataFrame) -> np.ndarray:
        encoded = frame[ALL_FEATURES].copy()
        for feature in CATEGORICAL_FEATURES:
            encoded[feature] = encoded[feature].map(
                lambda value: self._category_codes[feature].get(str(value), -1)
            )
        return encoded.to_numpy(dtype=float)

    def _predict_prices(self, encoded_rows: np.ndarray) -> np.ndarray:
        rows = np.atleast_2d(encoded_rows)
        frame = pd.DataFrame(rows, columns=ALL_FEATURES)
        for feature, levels in self._category_levels.items():
            frame[feature] = frame[feature].map(
                lambda code: (
                    levels[int(code)]
                    if float(code).is_integer() and 0 <= int(code) < len(levels)
                    else "__unknown_category__"
                )
            )
        return np.asarray(
            self.predictor.predict_many(frame.to_dict(orient="records")),
            dtype=float,
        )

    def explain(self, payload: dict, top_k: int = 7) -> dict:
        encoded_payload = self._encode_frame(pd.DataFrame([payload], columns=ALL_FEATURES))
        seed_input = json.dumps(
            [(feature, payload.get(feature)) for feature in ALL_FEATURES],
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        ).encode("utf-8")
        seed = int.from_bytes(hashlib.sha256(seed_input).digest()[:4], "big")
        with _SHAP_RANDOM_LOCK:
            random_state = np.random.get_state()
            try:
                np.random.seed(seed)
                values = self.explainer(
                    encoded_payload,
                    max_evals=self._max_evals,
                )
            finally:
                np.random.set_state(random_state)
        shap_row = np.asarray(values.values[0], dtype=float)
        base_value = float(np.asarray(values.base_values).reshape(-1)[0])
        predicted = float(self.predictor.predict_many([payload])[0])
        if not np.isclose(base_value + shap_row.sum(), predicted, rtol=1e-8, atol=0.01):
            raise RuntimeError("SHAP contributions did not reconcile with the model prediction.")

        ranked = sorted(
            zip(ALL_FEATURES, shap_row),
            key=lambda item: abs(item[1]),
            reverse=True,
        )
        contributions = [
            {
                "feature": FEATURE_DISPLAY_NAMES.get(feature, feature),
                "raw_feature": feature,
                "impact_rupees": float(impact),
                "direction": "increases" if impact >= 0 else "decreases",
                "value": payload.get(feature),
            }
            for feature, impact in ranked
        ]
        positive = [item for item in ranked if item[1] > 0]
        negative = [item for item in ranked if item[1] < 0]
        least_influential = sorted(ranked, key=lambda item: abs(item[1]))[:3]
        net_contribution = float(shap_row.sum())
        location = f"{payload.get('locality')}, {payload.get('city')}"
        property_type = str(payload.get("property_type", "property")).lower()
        difference_phrase = "above" if net_contribution >= 0 else "below"
        leading_feature = self._contribution(*ranked[0], payload) if ranked else None
        narrative = (
            f"For the {payload.get('bhk')} BHK {property_type} in {location}, "
            f"the model's estimate is {_format_inr(predicted)}. Its reference value "
            f"across {len(self._background)} training listings is {_format_inr(base_value)}; "
            f"this property's combined feature effects place it "
            f"{_format_inr(abs(net_contribution))} {difference_phrase} that reference. "
            + (
                f"{leading_feature['feature']} has the largest absolute contribution "
                f"({leading_feature['impact_rupees']:+,.0f} INR)."
                if leading_feature
                else "No feature contributions were available."
            )
        )

        return {
            "base_value": base_value,
            "predicted_value": predicted,
            "net_contribution": net_contribution,
            "contributions": contributions,
            "display_contributions": contributions[:max(1, min(top_k, 7))],
            "narrative": narrative,
            "positive_factors": [
                self._contribution(feature, impact, payload)
                for feature, impact in positive[:3]
            ],
            "negative_factors": [
                self._contribution(feature, impact, payload)
                for feature, impact in negative[:3]
            ],
            "most_influential": leading_feature,
            "least_influential": [
                self._contribution(feature, impact, payload)
                for feature, impact in least_influential
            ],
            "explainer_method": f"Permutation SHAP, {self.PERMUTATIONS} permutations",
            "background_size": len(self._background),
            "output_scale": "INR",
            "additivity_error": base_value + net_contribution - predicted,
        }

    @staticmethod
    def _contribution(feature: str, impact: float, payload: dict) -> dict:
        return {
            "feature": FEATURE_DISPLAY_NAMES.get(feature, feature),
            "raw_feature": feature,
            "impact_rupees": float(impact),
            "direction": "increases" if impact >= 0 else "decreases",
            "value": payload.get(feature),
        }


# ---------------------------------------------------------------------------
# 3. WhatIfEngine
# ---------------------------------------------------------------------------
class WhatIfEngine:
    """Re-runs inference on a modified copy of the base property to compute
    an instant price delta for sensitivity / what-if analysis."""

    def __init__(self, predictor: PropIntelPredictor):
        self.predictor = predictor

    def evaluate(self, base_payload: dict, changes: dict) -> dict:
        base_result = self.predictor.predict(base_payload)

        modified_payload = {**base_payload, **changes}
        modified_result = self.predictor.predict(modified_payload)

        base_price = base_result["predicted_price"]
        new_price = modified_result["predicted_price"]
        delta_abs = new_price - base_price
        delta_pct = (delta_abs / base_price) * 100 if base_price else 0.0

        return {
            "base_price": base_price,
            "new_price": new_price,
            "delta_abs": round(delta_abs, 0),
            "delta_pct": round(delta_pct, 2),
            "base_price_per_sqft": base_result["predicted_price_per_sqft"],
            "new_price_per_sqft": modified_result["predicted_price_per_sqft"],
            "base_reliability": {
                "is_reliable": base_result["is_reliable"],
                "warnings": base_result["reliability_warnings"],
            },
            "new_reliability": {
                "is_reliable": modified_result["is_reliable"],
                "warnings": modified_result["reliability_warnings"],
            },
            "changed_fields": {
                k: {"from": base_payload.get(k), "to": v} for k, v in changes.items()
            },
        }


# ---------------------------------------------------------------------------
# 4. RecommendationEngine
# ---------------------------------------------------------------------------
class RecommendationEngine:
    """Rule-based + distance-based scoring over the property catalog.

    match_score blends:
      - budget fit        (how close listed_price sits to the user's budget band)
      - value-for-money   (model estimate vs listed price, scaled by holdout MAPE)
      - preference distance (city / bhk / property_type / furnishing match)
    """

    WEIGHTS = {"budget_fit": 0.35, "value": 0.40, "preference": 0.25}

    def __init__(self, predictor: PropIntelPredictor, catalog: pd.DataFrame):
        self.predictor = predictor
        self.catalog = catalog

    def _budget_fit(self, price: float, budget_min: float, budget_max: float) -> float:
        if is_within_budget(price, budget_min, budget_max):
            return 1.0
        span = max(budget_max - budget_min, 1.0)
        dist = min(abs(price - budget_min), abs(price - budget_max))
        return max(0.0, 1 - dist / span)

    def _preference_distance(self, row: pd.Series, prefs: dict) -> float:
        score = 0.0
        total = 0.0
        if prefs.get("city"):
            total += 1
            score += 1.0 if row["city"] == prefs["city"] else 0.0
        if prefs.get("bhk"):
            total += 1
            score += 1.0 if row["bhk"] == prefs["bhk"] else max(
                0.0, 1 - abs(row["bhk"] - prefs["bhk"]) / 4
            )
        if prefs.get("property_type"):
            total += 1
            score += 1.0 if row["property_type"] == prefs["property_type"] else 0.0
        if prefs.get("furnishing"):
            total += 1
            score += 1.0 if row["furnishing"] == prefs["furnishing"] else 0.5
        return score / total if total else 1.0

    def _filter_catalog(self, prefs: dict) -> pd.DataFrame:
        df = self.catalog.copy()
        budget_min = prefs.get("budget_min", 0)
        budget_max = prefs.get("budget_max", df["listed_price"].max())
        df = filter_properties_by_budget(df, budget_min, budget_max)
        if "model_estimate" in df.columns:
            estimates = pd.to_numeric(df["model_estimate"], errors="coerce")
            df = df.loc[estimates.between(budget_min, budget_max, inclusive="both")].copy()

        if prefs.get("city"):
            df = df[df["city"] == prefs["city"]]
        if prefs.get("bhk"):
            df = df[df["bhk"].between(prefs["bhk"] - 1, prefs["bhk"] + 1)]
        return df

    def recommend_with_count(self, prefs: dict, top_n: int = 6) -> tuple[list, int]:
        df = self._filter_catalog(prefs)
        budget_min = prefs.get("budget_min", 0)
        budget_max = prefs.get("budget_max", self.catalog["listed_price"].max())
        results = []
        for _, row in df.iterrows():
            budget_fit = self._budget_fit(row["listed_price"], budget_min, budget_max)
            model_estimate = float(row["model_estimate"])
            listed_price = float(row["listed_price"])
            price_difference_pct = (
                abs(model_estimate - listed_price) / listed_price * 100
                if listed_price > 0
                else None
            )
            mape = self.predictor.metrics.get("mape")
            agreement_reference = (
                float(mape)
                if isinstance(mape, (int, float)) and np.isfinite(mape) and mape > 0
                else None
            )
            if price_difference_pct is None or agreement_reference is None:
                price_agreement = None
            elif price_difference_pct <= agreement_reference:
                price_agreement = "close"
            elif price_difference_pct <= agreement_reference * 2:
                price_agreement = "moderate"
            else:
                price_agreement = "large"
            feature_payload = {feature: row[feature] for feature in ALL_FEATURES}
            reliability = self.predictor.assess_reliability(feature_payload)
            undervaluation = (model_estimate - listed_price) / model_estimate
            has_error_scale = (
                isinstance(mape, (int, float))
                and np.isfinite(mape)
                and mape > 0
            )
            value_score = 0.5
            if reliability["is_reliable"] and has_error_scale:
                error_scale = float(mape) / 100
                scaled_value_signal = undervaluation / error_scale
                value_score = float(
                    0.5
                    + 0.5
                    * scaled_value_signal
                    / (1 + abs(scaled_value_signal))
                )
            pref_score = self._preference_distance(row, prefs)

            match_score = (
                self.WEIGHTS["budget_fit"] * budget_fit
                + self.WEIGHTS["value"] * value_score
                + self.WEIGHTS["preference"] * pref_score
            ) * 100

            is_deal = (
                reliability["is_reliable"]
                and listed_price < model_estimate * 0.95
            )

            results.append(
                {
                    "id": str(row["id"]),
                    "city": str(row["city"]),
                    "locality": str(row["locality"]),
                    "property_type": str(row["property_type"]),
                    "bhk": int(row["bhk"]),
                    "area_sqft": float(row["area_sqft"]),
                    "listed_price": listed_price,
                    "fair_price": model_estimate,
                    "source_verified": bool(row.get("source_verified", False)),
                    "price_difference_pct": price_difference_pct,
                    "price_agreement": price_agreement,
                    "match_score": round(match_score, 1),
                    "is_deal": bool(is_deal),
                    "variance_pct": round(
                        (listed_price - model_estimate) / model_estimate * 100, 1
                    ),
                    **reliability,
                }
            )

        results.sort(
            key=lambda result: (
                result["price_difference_pct"]
                if result["price_difference_pct"] is not None
                else float("inf"),
                not (result["source_verified"] and result["is_reliable"]),
                -result["match_score"],
            )
        )
        return results[:top_n], len(results)

    def recommend(self, prefs: dict, top_n: int = 6) -> list:
        results, _ = self.recommend_with_count(prefs, top_n)
        return results
