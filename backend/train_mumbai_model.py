from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import GroupKFold, GroupShuffleSplit
from sklearn.pipeline import Pipeline
from xgboost import XGBRegressor

from ml_engine import ALL_FEATURES, build_preprocessor, build_training_profile, prepare_mumbai_dataset

RAW_DATASET_PATH = Path(__file__).resolve().parents[1] / "dataset" / "mumbai.csv"
CANDIDATE_MODEL_PATH = Path(__file__).resolve().parent / "models" / "mumbai_model_candidate.joblib"
FEATURE_COLUMNS = ALL_FEATURES


def _grouped_train_test_split(
    features: pd.DataFrame,
    target: pd.Series,
    test_size: float = 0.2,
    random_state: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, np.ndarray]:
    groups = pd.util.hash_pandas_object(features[FEATURE_COLUMNS], index=False).to_numpy()
    splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=random_state)
    train_indices, test_indices = next(splitter.split(features, target, groups=groups))
    return (
        features.iloc[train_indices],
        features.iloc[test_indices],
        target.iloc[train_indices],
        target.iloc[test_indices],
        groups[train_indices],
    )


def build_clean_dataset(csv_path: Path | str = RAW_DATASET_PATH) -> pd.DataFrame:
    """Use the same parsing and outlier policy as the serving API."""
    return prepare_mumbai_dataset(csv_path)


def _build_model(model_name: str):
    if model_name == "RandomForest":
        return RandomForestRegressor(
            n_estimators=350,
            max_depth=18,
            random_state=42,
            n_jobs=-1,
        )
    if model_name == "GradientBoosting":
        return GradientBoostingRegressor(
            n_estimators=300,
            max_depth=3,
            learning_rate=0.04,
            loss="huber",
            random_state=42,
        )
    if model_name == "XGBoost":
        return XGBRegressor(
            n_estimators=400,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.85,
            colsample_bytree=0.85,
            reg_lambda=1.0,
            random_state=42,
            n_jobs=-1,
        )
    if model_name == "LinearRegression":
        return LinearRegression()
    raise ValueError(f"Unsupported model candidate: {model_name}")


def _build_pipeline(model_name: str) -> Pipeline:
    return Pipeline(
        [
            ("preprocessor", build_preprocessor()),
            ("model", _build_model(model_name)),
        ]
    )


def train_and_evaluate_models(clean_df: pd.DataFrame) -> dict:
    X = clean_df[FEATURE_COLUMNS].copy()
    y = clean_df["fair_price"].astype(float)
    target_columns = {
        "total_price": "fair_price",
        "price_per_sqft": "price_per_sqft",
    }
    X_train, X_test, y_train, y_test, train_groups = _grouped_train_test_split(X, y)

    cross_validation = GroupKFold(n_splits=5)
    candidates = [
        (model_name, target_representation, target_transform)
        for model_name in ("LinearRegression", "RandomForest", "GradientBoosting", "XGBoost")
        for target_representation in ("total_price", "price_per_sqft")
        for target_transform in ("none", "log1p")
        if (target_representation == "total_price" or model_name != "LinearRegression")
        and (target_transform == "none" or model_name in {"RandomForest", "XGBoost"})
    ]
    cv_results = []
    for model_name, target_representation, target_transform in candidates:
        target_column = target_columns[target_representation]
        candidate_target = clean_df[target_column].astype(float)
        candidate_train_target = candidate_target.loc[X_train.index]
        fold_mae = []
        for train_indices, validation_indices in cross_validation.split(
            X_train, groups=train_groups
        ):
            fold_train_x = X_train.iloc[train_indices]
            fold_validation_x = X_train.iloc[validation_indices]
            fold_train_y = candidate_train_target.iloc[train_indices].to_numpy()
            fold_validation_y = y_train.iloc[validation_indices]
            if target_transform == "log1p":
                fold_train_y = np.log1p(fold_train_y)
            fold_pipeline = _build_pipeline(model_name)
            fold_pipeline.fit(fold_train_x, fold_train_y)
            fold_predictions = fold_pipeline.predict(fold_validation_x)
            if target_transform == "log1p":
                fold_predictions = np.expm1(fold_predictions)
            if target_representation == "price_per_sqft":
                fold_predictions = fold_predictions * fold_validation_x["area_sqft"].to_numpy()
            fold_mae.append(mean_absolute_error(fold_validation_y, fold_predictions))

        evaluation_pipeline = _build_pipeline(model_name)
        evaluation_target = candidate_train_target.to_numpy()
        if target_transform == "log1p":
            evaluation_target = np.log1p(evaluation_target)
        evaluation_pipeline.fit(X_train, evaluation_target)
        predictions = evaluation_pipeline.predict(X_test)
        if target_transform == "log1p":
            predictions = np.expm1(predictions)
        if target_representation == "price_per_sqft":
            predictions = predictions * X_test["area_sqft"].to_numpy()
        test_metrics = {
            "mae": float(mean_absolute_error(y_test, predictions)),
            "rmse": float(np.sqrt(mean_squared_error(y_test, predictions))),
            "r2": float(r2_score(y_test, predictions)),
            "mape": float(
                np.mean(np.abs((y_test.to_numpy() - predictions) / y_test.to_numpy())) * 100
            ),
            "mean_error": float(np.mean(predictions - y_test.to_numpy())),
        }
        cv_results.append(
            {
                "model": model_name,
                "target_representation": target_representation,
                "target_transform": target_transform,
                "target_column": target_column,
                "cv_mae": float(np.mean(fold_mae)),
                "cv_mae_std": float(np.std(fold_mae)),
                "fold_mae": [float(score) for score in fold_mae],
                "test_metrics": test_metrics,
            }
        )

    best_cv = min(cv_results, key=lambda result: result["cv_mae"])
    best_name = best_cv["model"]
    best_target_representation = best_cv["target_representation"]
    best_target_transform = best_cv["target_transform"]
    best_target_column = best_cv["target_column"]
    metrics = {
        **best_cv["test_metrics"],
        "cv_mae": best_cv["cv_mae"],
        "cv_mae_std": best_cv["cv_mae_std"],
    }

    print("\nFive-fold CV and held-out test results:")
    for result in sorted(cv_results, key=lambda item: item["cv_mae"]):
        print(
            f"{result['model']} ({result['target_representation']}, "
            f"{result['target_transform']}): "
            f"CV MAE={result['cv_mae']:.0f} "
            f"(std={result['cv_mae_std']:.0f}); "
            f"test MAE={result['test_metrics']['mae']:.0f}, "
            f"RMSE={result['test_metrics']['rmse']:.0f}, "
            f"R²={result['test_metrics']['r2']:.4f}, "
            f"MAPE={result['test_metrics']['mape']:.2f}%, "
            f"bias={result['test_metrics']['mean_error']:.0f}"
        )
    print(
        f"Selected {best_name} ({best_target_representation}, {best_target_transform}) "
        "by cross-validation MAE; "
        f"held-out bias={metrics['mean_error']:.0f}"
    )

    final_pipeline = _build_pipeline(best_name)
    final_target = clean_df[best_target_column].astype(float).to_numpy()
    if best_target_transform == "log1p":
        final_target = np.log1p(final_target)
    final_pipeline.fit(X, final_target)
    return {
        "model": best_name,
        "target_representation": best_target_representation,
        "target_transform": best_target_transform,
        "target_column": best_target_column,
        "pipeline": final_pipeline,
        "metrics": metrics,
        "cv_results": cv_results,
        "feature_columns": FEATURE_COLUMNS,
        "training_profile": build_training_profile(clean_df),
        "training_rows": len(clean_df),
    }


def save_best_model(best_result: dict, output_path: Path | str = CANDIDATE_MODEL_PATH) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    artifact = {
        "artifact_version": 5,
        "pipeline": best_result["pipeline"],
        "feature_columns": best_result["feature_columns"],
        "target_column": best_result["target_column"],
        "target_representation": best_result["target_representation"],
        "target_transform": best_result["target_transform"],
        "model_name": best_result["model"],
        "metrics": best_result["metrics"],
        "cv_results": best_result["cv_results"],
        "training_profile": best_result["training_profile"],
        "training_rows": best_result["training_rows"],
    }
    joblib.dump(artifact, path)
    print(f"Saved best model to {path}")
    return path


def train_mumbai_model(
    csv_path: Path | str = RAW_DATASET_PATH,
    output_path: Path | str = CANDIDATE_MODEL_PATH,
):
    clean_df = build_clean_dataset(csv_path)
    best = train_and_evaluate_models(clean_df)
    save_best_model(best, output_path)
    return clean_df, best


if __name__ == "__main__":
    train_mumbai_model()
