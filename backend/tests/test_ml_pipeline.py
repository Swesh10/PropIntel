from pathlib import Path
import unittest

import joblib
import pandas as pd
from pydantic import ValidationError

from app import PropertyInput, RecommendInput, WhatIfInput
from ml_engine import (
    ALL_FEATURES,
    PropIntelPredictor,
    XAIExplainer,
    _parse_price_to_inr,
    build_preprocessor,
    build_training_profile,
    cross_validated_catalog_estimates,
    filter_properties_by_budget,
    normalize_furnishing,
    normalize_property_type,
    prepare_mumbai_dataset,
    variance_percentage,
)
from ml_engine import RecommendationEngine
from train_mumbai_model import _grouped_train_test_split, build_clean_dataset


class MumbaiPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = prepare_mumbai_dataset()
        model_path = Path(__file__).resolve().parents[1] / "models" / "mumbai_model_v5.joblib"
        artifact = joblib.load(model_path)
        cls.predictor = PropIntelPredictor(model_type="random_forest")
        cls.predictor.pipeline = artifact["pipeline"]
        cls.predictor.preprocessor = artifact["pipeline"].named_steps["preprocessor"]
        cls.predictor.model = artifact["pipeline"].named_steps["model"]
        cls.predictor.is_fitted = True
        cls.predictor.training_profile = artifact["training_profile"]
        cls.predictor.target_representation = artifact["target_representation"]
        cls.predictor._use_log_target = artifact["target_transform"] == "log1p"
        cls.predictor.metrics = artifact["metrics"]
        cls.explainer = XAIExplainer(cls.predictor, cls.dataset)

    def test_training_and_serving_use_identical_cleaning(self):
        training_data = build_clean_dataset()
        self.assertTrue(training_data.equals(self.dataset))
        self.assertEqual(self.dataset["source_verified"].dtype, bool)
        self.assertNotIn("listed_price", ALL_FEATURES)
        self.assertNotIn("fair_price", ALL_FEATURES)
        self.assertTrue(self.dataset["price_per_sqft"].between(3_000, 80_000).all())

    def test_catalog_estimates_are_generated_from_excluded_training_folds(self):
        sample = self.dataset.iloc[:80].copy()
        estimates = cross_validated_catalog_estimates(
            self.predictor,
            sample,
            n_splits=4,
        )

        self.assertEqual(estimates.shape, (len(sample),))
        self.assertTrue(pd.Series(estimates).gt(0).all())
        self.assertTrue(pd.Series(estimates).map(pd.notna).all())

    def test_training_preprocessor_uses_serving_feature_order(self):
        preprocessor = build_preprocessor()
        preprocessor.fit(self.dataset[ALL_FEATURES])
        self.assertEqual(list(preprocessor.feature_names_in_), ALL_FEATURES)
        self.assertNotIn("bedrooms", ALL_FEATURES)
        self.assertNotIn("bathrooms", ALL_FEATURES)
        self.assertNotIn("parking", ALL_FEATURES)

    def test_price_parser_converts_lakh_and_crore_to_rupees(self):
        self.assertEqual(_parse_price_to_inr("52.5 Lakh"), 5_250_000)
        self.assertEqual(_parse_price_to_inr("1.41 Cr"), 14_100_000)
        self.assertEqual(_parse_price_to_inr("78 L - 1.02 Cr"), 7_800_000)
        self.assertEqual(_parse_price_to_inr("2.68 - 3.17 Cr"), 26_800_000)
        self.assertEqual(_parse_price_to_inr("3.8 Cr Onwards"), 38_000_000)

    def test_variance_uses_listed_minus_estimate_over_estimate(self):
        self.assertAlmostEqual(variance_percentage(5_250_000, 14_100_000), -62.7659574, places=5)

    def test_budget_filter_returns_only_properties_inclusive_of_range(self):
        properties = self.dataset.iloc[:50]
        minimum = float(properties["listed_price"].min())
        maximum = float(properties["listed_price"].median())
        filtered = filter_properties_by_budget(properties, minimum, maximum)
        self.assertTrue(filtered["listed_price"].between(minimum, maximum).all())
        self.assertFalse(filtered.empty)

    def test_recommendations_filter_listed_and_estimated_prices_inclusive_of_budget(self):
        catalog = pd.concat([self.dataset.iloc[[0]]] * 5, ignore_index=True)
        prices = [4_500_000, 5_000_000, 7_500_000, 10_000_000, 12_000_000]
        catalog["id"] = [f"budget-{index}" for index in range(len(prices))]
        catalog["listed_price"] = prices
        catalog["model_estimate"] = prices
        engine = RecommendationEngine(self.predictor, catalog)

        results, matching_count = engine.recommend_with_count(
            {"budget_min": 5_000_000, "budget_max": 10_000_000},
            top_n=100,
        )

        self.assertEqual(matching_count, 3)
        self.assertEqual(len(results), 3)
        self.assertEqual(
            {result["listed_price"] for result in results},
            {5_000_000, 7_500_000, 10_000_000},
        )
        self.assertTrue(
            all(
                5_000_000 <= result["fair_price"] <= 10_000_000
                for result in results
            )
        )

    def test_recommendations_rank_by_price_agreement_and_keep_match_score(self):
        class ReliableStub:
            metrics = {"mape": 17.0}

            def assess_reliability(self, payload):
                return {"is_reliable": True, "reliability_warnings": []}

        catalog = pd.concat([self.dataset.iloc[[0]]] * 3, ignore_index=True)
        catalog["id"] = ["large-gap", "moderate-gap", "close-gap"]
        catalog["listed_price"] = 15_000_000
        catalog["model_estimate"] = [22_500_000, 17_800_000, 15_500_000]
        catalog["source_verified"] = [True, True, False]

        results, matching_count = RecommendationEngine(
            ReliableStub(), catalog
        ).recommend_with_count(
            {"budget_min": 0, "budget_max": 30_000_000},
            top_n=3,
        )

        self.assertEqual(matching_count, 3)
        self.assertEqual([result["id"] for result in results], [
            "close-gap",
            "moderate-gap",
            "large-gap",
        ])
        self.assertAlmostEqual(results[0]["price_difference_pct"], 3.333333, places=5)
        self.assertEqual(
            [result["price_agreement"] for result in results],
            ["close", "moderate", "large"],
        )
        self.assertFalse(results[0]["source_verified"])
        self.assertTrue(results[1]["source_verified"])
        self.assertTrue(results[2]["source_verified"])
        self.assertTrue(all("match_score" in result for result in results))

    def test_recommendations_do_not_fall_back_outside_budget_or_preferences(self):
        catalog = self.dataset.copy()
        catalog["model_estimate"] = self.predictor.predict_many(
            catalog[ALL_FEATURES].to_dict("records")
        )
        engine = RecommendationEngine(self.predictor, catalog)
        city = self.dataset["city"].value_counts().index[0]
        city_rows = self.dataset[
            (self.dataset["city"] == city) & self.dataset["bhk"].between(1, 3)
        ]
        minimum = float(city_rows["listed_price"].quantile(0.25))
        maximum = float(city_rows["listed_price"].quantile(0.75))
        results = engine.recommend(
            {"city": city, "bhk": 2, "budget_min": minimum, "budget_max": maximum},
            top_n=100,
        )
        self.assertTrue(results)
        for result in results:
            self.assertGreaterEqual(result["listed_price"], minimum)
            self.assertLessEqual(result["listed_price"], maximum)
            self.assertGreaterEqual(result["fair_price"], minimum)
            self.assertLessEqual(result["fair_price"], maximum)
            self.assertEqual(result["city"], city)
            self.assertIn(result["bhk"], (1, 2, 3))

        no_matches = engine.recommend(
            {"city": "No such city", "bhk": 2, "budget_min": minimum, "budget_max": maximum},
            top_n=100,
        )
        self.assertEqual(no_matches, [])

    def test_recommendation_estimates_come_from_model_and_unreliable_rows_are_not_tagged_as_deals(self):
        catalog = self.dataset.iloc[:100].copy()
        catalog["model_estimate"] = self.predictor.predict_many(
            catalog[ALL_FEATURES].to_dict("records")
        )
        row = catalog.iloc[0]
        payload = {feature: row[feature] for feature in ALL_FEATURES}
        reliability = self.predictor.assess_reliability(payload)
        results = RecommendationEngine(self.predictor, catalog).recommend(
            {
                "budget_min": 0,
                "budget_max": max(
                    float(catalog["listed_price"].max()),
                    float(catalog["model_estimate"].max()),
                ),
            },
            top_n=100,
        )

        result = next(item for item in results if item["id"] == row["id"])
        self.assertAlmostEqual(result["fair_price"], row["model_estimate"])
        self.assertEqual(result["is_reliable"], reliability["is_reliable"])
        if not reliability["is_reliable"]:
            self.assertFalse(result["is_deal"])

    def test_recommendation_fit_score_is_a_relative_ranking_not_a_perfect_match_probability(self):
        catalog = self.dataset.iloc[[0]].copy()
        row = catalog.iloc[0]
        catalog["model_estimate"] = float(row["listed_price"])
        results = RecommendationEngine(self.predictor, catalog).recommend(
            {
                "city": row["city"],
                "bhk": int(row["bhk"]),
                "property_type": row["property_type"],
                "furnishing": row["furnishing"],
                "budget_min": float(row["listed_price"]),
                "budget_max": float(row["listed_price"]) * 2,
            },
            top_n=1,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["match_score"], 80.0)
        self.assertFalse(results[0]["is_deal"])

    def test_large_price_difference_does_not_saturate_the_recommendation_fit_score(self):
        class ReliableStub:
            metrics = {"mape": 20.0}

            def assess_reliability(self, payload):
                return {"is_reliable": True, "reliability_warnings": []}

        catalog = self.dataset.iloc[[0]].copy()
        row = catalog.iloc[0]
        catalog["model_estimate"] = float(row["listed_price"]) * 2
        results = RecommendationEngine(ReliableStub(), catalog).recommend(
            {
                "city": row["city"],
                "bhk": int(row["bhk"]),
                "property_type": row["property_type"],
                "furnishing": row["furnishing"],
                "budget_min": float(row["listed_price"]),
                "budget_max": float(catalog["model_estimate"].max()),
            },
            top_n=1,
        )

        self.assertLess(results[0]["match_score"], 100)
        self.assertAlmostEqual(results[0]["match_score"], 94.3, places=1)

    def test_unusual_and_sparse_inputs_are_flagged(self):
        profile = build_training_profile(self.dataset)
        predictor = PropIntelPredictor()
        predictor.training_profile = profile

        supported_city = max(profile["locality_counts"], key=lambda city: max(profile["locality_counts"][city].values()))
        supported_locality = max(
            profile["locality_counts"][supported_city],
            key=profile["locality_counts"][supported_city].get,
        )
        payload = {
            feature: (bounds[0] + bounds[1]) / 2
            for feature, bounds in profile["numeric_ranges"].items()
        }
        payload.update(
            {
                feature: values[0]
                for feature, values in profile["categories"].items()
            }
        )
        payload["city"] = supported_city
        payload["locality"] = supported_locality
        self.assertTrue(predictor.assess_reliability(payload)["is_reliable"])

        payload["area_sqft"] = profile["numeric_ranges"]["area_sqft"][1] + 10_000
        reliability = predictor.assess_reliability(payload)
        self.assertFalse(reliability["is_reliable"])
        self.assertTrue(reliability["reliability_warnings"])

    def test_property_type_and_furnishing_categories_are_normalized_strictly(self):
        self.assertEqual(normalize_property_type("Residential Apartment"), "Apartment")
        self.assertEqual(normalize_property_type("Studio Apartment"), "Studio Apartment")
        self.assertEqual(normalize_property_type("Independent House/Villa"), "Villa")
        self.assertIsNone(normalize_property_type("Residential Land"))
        self.assertEqual(normalize_furnishing("1"), "Semi-Furnished")
        self.assertIsNone(normalize_furnishing("unknown"))
        with self.assertRaises(ValidationError):
            PropertyInput(
                city="Mumbai",
                locality="Taloja",
                property_type="Residential Land",
                bhk=2,
                area_sqft=850,
            )
        self.assertEqual(
            set(self.dataset["property_type"].unique()),
            {"Apartment", "Studio Apartment", "Villa"},
        )

    def test_price_prediction_accepts_unfurnished_and_furnished_model_inputs(self):
        source = self.dataset.iloc[0]
        payload = {feature: source[feature] for feature in ALL_FEATURES}

        for furnishing in ("Unfurnished", "Semi-Furnished"):
            with self.subTest(furnishing=furnishing):
                result = self.predictor.predict({**payload, "furnishing": furnishing})
                self.assertGreater(result["predicted_price"], 0)
                self.assertGreater(result["predicted_price_per_sqft"], 0)

    def test_recommendation_input_normalizes_categories_and_rejects_invalid_ranges(self):
        payload = RecommendInput(
            city=" Central Mumbai suburbs ",
            bhk=2,
            property_type="Residential Apartment",
            furnishing="semi furnished",
            budget_min=1_000_000,
            budget_max=5_000_000,
        )
        self.assertEqual(payload.city, "Central Mumbai suburbs")
        self.assertEqual(payload.property_type, "Apartment")
        self.assertEqual(payload.furnishing, "Semi-Furnished")
        self.assertIsNone(RecommendInput(city="").city)
        with self.assertRaises(ValidationError):
            RecommendInput(bhk=0)
        with self.assertRaises(ValidationError):
            RecommendInput(budget_min=5_000_000, budget_max=1_000_000)
        with self.assertRaises(ValidationError):
            RecommendInput(top_n=51)

    def test_parking_is_not_fabricated_as_a_model_feature_and_nonzero_is_flagged(self):
        self.assertNotIn("parking", ALL_FEATURES)
        profile = build_training_profile(self.dataset)
        payload = self.dataset.iloc[0][ALL_FEATURES].to_dict()
        predictor = PropIntelPredictor()
        predictor.training_profile = profile
        zero_parking = predictor.assess_reliability({**payload, "parking": 0})
        self.assertFalse(any("Parking details are not represented" in item for item in zero_parking["reliability_warnings"]))
        parking_result = predictor.assess_reliability({**payload, "parking": 2})
        self.assertFalse(parking_result["is_reliable"])
        self.assertTrue(any("Parking details are not represented" in item for item in parking_result["reliability_warnings"]))

    def test_sparse_studio_category_is_modeled_separately_and_flagged(self):
        studio = self.dataset[self.dataset["property_type"] == "Studio Apartment"].iloc[0]
        payload = {feature: studio[feature] for feature in ALL_FEATURES}
        result = self.predictor.predict(payload)
        self.assertFalse(result["is_reliable"])
        self.assertTrue(
            any(
                "Property Type (Studio Apartment) has limited examples" in warning
                for warning in result["reliability_warnings"]
            )
        )

    def test_api_normalizes_supported_inputs_and_rejects_inconsistent_values(self):
        payload = PropertyInput(
            city=" Mumbai ",
            locality=" Taloja ",
            property_type="Residential Apartment",
            bhk=2,
            area_sqft=850,
            floor=4,
            total_floors=10,
            amenities=["Lift", "lift"],
            listed_price=0,
        )
        normalized = payload.to_payload()
        self.assertEqual(normalized["property_type"], "Apartment")
        self.assertEqual(normalized["city"], "Mumbai")
        self.assertEqual(normalized["amenities"], ["Lift"])
        self.assertEqual(normalized["amenities_count"], 1)
        self.assertIsNone(normalized["listed_price"])
        self.assertEqual(normalized["total_floors"], 10)
        default_height = PropertyInput(
            city="Mumbai",
            locality="Taloja",
            property_type="Apartment",
            bhk=2,
            area_sqft=850,
            floor=4,
        )
        self.assertEqual(default_height.to_payload()["total_floors"], 5)

        invalid_payloads = [
            {"floor": 11, "total_floors": 10},
            {"bedrooms": 3},
            {"parking": -1},
            {"listed_price": -100},
            {"area_sqft": float("inf")},
            {"amenities": ["Unknown amenity"]},
        ]
        base = {
            "city": "Mumbai",
            "locality": "Taloja",
            "property_type": "Apartment",
            "bhk": 2,
            "area_sqft": 850,
        }
        for invalid in invalid_payloads:
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                PropertyInput(**{**base, **invalid})

        valid_base = PropertyInput(**base, floor=4, total_floors=10)
        WhatIfInput(base=valid_base, changes={"bhk": 3, "bedrooms": 3, "amenities_count": 4})
        for invalid_changes in (
            {"area_sqft": 0},
            {"floor": 11},
            {"amenities_count": -1},
            {"unknown_field": 2},
        ):
            with self.subTest(invalid_changes=invalid_changes), self.assertRaises(ValidationError):
                WhatIfInput(base=valid_base, changes=invalid_changes)

    def test_zero_listed_price_is_treated_as_not_provided(self):
        row = self.dataset.iloc[0]
        payload = {feature: row[feature] for feature in ALL_FEATURES}
        payload.update({"area_sqft": float(row["area_sqft"]), "listed_price": 0})
        result = self.predictor.predict(payload)
        self.assertIsNone(result["listed_price"])
        self.assertIsNone(result["delta_pct"])
        self.assertIsNone(result["verdict"])
        self.assertIsNone(result["confidence_score"])
        self.assertTrue(any("Bathroom count" in item for item in result["limitations"]))

    def test_single_prediction_and_explanation_share_identical_inference(self):
        row = self.dataset.loc[self.dataset["listed_price"].idxmax()]
        payload = {feature: row[feature] for feature in ALL_FEATURES}
        payload["area_sqft"] = float(row["area_sqft"])
        payload["amenities_count"] = 3
        result = self.predictor.predict(payload)
        explanation = self.explainer.explain(payload)
        self.assertAlmostEqual(
            result["predicted_price"],
            explanation["predicted_value"],
            delta=1,
        )
        self.assertLess(abs(explanation["additivity_error"]), 0.01)

    def test_same_property_explanation_is_reproducible(self):
        row = self.dataset.loc[
            (self.dataset["city"] == "Central Mumbai suburbs")
            & (self.dataset["locality"] == "Powai")
        ].iloc[0]
        payload = {feature: row[feature] for feature in ALL_FEATURES}
        payload["area_sqft"] = 850.0
        payload.update(
            {
                "bhk": 2,
                "age_years": 3,
                "floor": 5,
                "total_floors": 6,
                "amenities_count": 3,
                "furnishing": "Semi-Furnished",
            }
        )

        first = self.explainer.explain(payload)
        second = self.explainer.explain(payload)

        self.assertEqual(first["contributions"], second["contributions"])
        self.assertEqual(first["predicted_value"], second["predicted_value"])
        self.assertEqual(first["base_value"], second["base_value"])

    def test_grouped_holdout_prevents_duplicate_feature_rows_crossing_splits(self):
        features = self.dataset[ALL_FEATURES]
        target = self.dataset["fair_price"]
        train_x, test_x, _, _, _ = _grouped_train_test_split(features, target)
        train_rows = set(map(tuple, train_x.astype(str).to_numpy()))
        test_rows = set(map(tuple, test_x.astype(str).to_numpy()))
        self.assertFalse(train_rows.intersection(test_rows))

    def test_property_specific_shap_explanations_reconcile_in_currency(self):
        examples = [
            ("Taloja", 2),
            ("Bhandup West", 2),
            ("Kalyan West", 2),
            ("Vikhroli East", 2),
            ("New Panvel", 1),
        ]
        predictions = []
        contribution_signatures = []
        explanations = []

        for locality, bhk in examples:
            matches = self.dataset[
                (self.dataset["locality"] == locality) & (self.dataset["bhk"] == bhk)
            ]
            self.assertFalse(matches.empty, f"No catalog example for {locality}, {bhk} BHK.")
            row = matches.iloc[0]
            payload = {feature: row[feature] for feature in ALL_FEATURES}
            payload["area_sqft"] = float(row["area_sqft"])
            payload["bhk"] = int(row["bhk"])
            result = self.predictor.predict(payload)
            explanation = self.explainer.explain(payload)

            self.assertEqual(explanation["output_scale"], "INR")
            self.assertEqual(len(explanation["contributions"]), len(ALL_FEATURES))
            self.assertAlmostEqual(
                explanation["base_value"]
                + sum(item["impact_rupees"] for item in explanation["contributions"]),
                explanation["predicted_value"],
                delta=0.01,
            )
            self.assertAlmostEqual(
                explanation["predicted_value"],
                result["predicted_price"],
                delta=1.0,
            )
            self.assertLess(abs(explanation["additivity_error"]), 0.01)
            self.assertEqual(len(explanation["display_contributions"]), 7)
            self.assertTrue(explanation["positive_factors"] or explanation["negative_factors"])

            predictions.append(result["predicted_price"])
            contribution_signatures.append(
                tuple(round(item["impact_rupees"], 2) for item in explanation["contributions"])
            )
            explanations.append(explanation["narrative"])

        self.assertGreater(len(set(predictions)), 1)
        self.assertEqual(len(set(contribution_signatures)), len(examples))
        self.assertEqual(len(set(explanations)), len(examples))

    def test_area_bhk_age_height_and_property_type_reach_prediction(self):
        row = self.dataset[
            (self.dataset["locality"] == "Taloja") & (self.dataset["bhk"] == 2)
        ].iloc[0]
        payload = {feature: row[feature] for feature in ALL_FEATURES}
        payload["area_sqft"] = float(row["area_sqft"])
        baseline = self.predictor.predict_many([payload])[0]

        variants = [
            {**payload, "area_sqft": payload["area_sqft"] + 300},
            {**payload, "bhk": 3, "bedrooms": 3},
            {**payload, "age_years": payload["age_years"] + 10},
            {**payload, "total_floors": payload["total_floors"] + 10},
        ]
        variant_prices = [self.predictor.predict_many([variant])[0] for variant in variants]
        self.assertTrue(all(abs(price - baseline) > 1 for price in variant_prices))

        alternate_type = {**payload, "property_type": "Villa"}
        self.assertNotEqual(
            self.explainer._encode_frame(
                pd.DataFrame([payload], columns=ALL_FEATURES)
            )[0, ALL_FEATURES.index("property_type")],
            self.explainer._encode_frame(
                pd.DataFrame([alternate_type], columns=ALL_FEATURES)
            )[0, ALL_FEATURES.index("property_type")],
        )
        self.assertIn(
            "property_type",
            {item["raw_feature"] for item in self.explainer.explain(payload)["contributions"]},
        )


if __name__ == "__main__":
    unittest.main()
