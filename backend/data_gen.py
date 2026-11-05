"""
PropIntel :: data_gen.py
-------------------------------------------------
Synthetic-but-realistic Maharashtra residential real-estate dataset generator.

Produces a Pandas DataFrame (and optionally persists to CSV/SQLite) that backs
the PropIntelPredictor training pipeline and the /api/compare, /api/recommend
and /api/market-trends endpoints.

City price anchors are loosely modelled on real relative price tiers
(Mumbai >> Pune > Nashik > Kolhapur ~ Satara > Sangli) purely for a
believable demo; this is NOT sourced from a licensed listings feed.
"""

import numpy as np
import pandas as pd

RNG_SEED = 42

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

CITIES = ["Mumbai", "Pune", "Nashik", "Kolhapur", "Sangli", "Satara", "Nagpur"]

# Base price per sq.ft (₹) and a locality multiplier spread per city
CITY_BASE_PSF = {
    "Mumbai": 18500,
    "Pune": 8200,
    "Nagpur": 5400,
    "Nashik": 5600,
    "Kolhapur": 4600,
    "Satara": 4100,
    "Sangli": 3800,
}

LOCALITIES = {
    "Mumbai": ["Andheri West", "Bandra East", "Powai", "Thane West", "Chembur", "Borivali", "Dadar"],
    "Pune": ["Baner", "Hinjewadi", "Kothrud", "Viman Nagar", "Wakad", "Hadapsar", "Kharadi"],
    "Nashik": ["Gangapur Road", "College Road", "Indira Nagar", "Nashik Road", "Panchavati"],
    "Kolhapur": ["Rajarampuri", "Tarabai Park", "Kalamba", "Shivaji Peth"],
    "Sangli": ["Vishrambag", "Sangliwadi", "Miraj Road"],
    "Satara": ["Sadar Bazar", "Powai Naka", "Guruwar Peth"],
    "Nagpur": ["Dharampeth", "Civil Lines", "Manish Nagar", "Wardha Road"],
}

PROPERTY_TYPES = ["Apartment", "Independent House", "Villa", "Row House"]
FURNISHING = ["Unfurnished", "Semi-Furnished", "Furnished"]
AMENITIES_POOL = [
    "Lift", "Power Backup", "Parking", "Gym", "Swimming Pool", "Club House",
    "Security", "Garden", "Children Play Area", "Rainwater Harvesting",
]


def _sample_amenities(rng: np.random.Generator) -> list:
    k = rng.integers(2, 8)
    return list(rng.choice(AMENITIES_POOL, size=k, replace=False))


def generate_dataset(n: int = 2200, seed: int = RNG_SEED) -> pd.DataFrame:
    """Generate a synthetic Maharashtra housing dataset with n rows."""
    rng = np.random.default_rng(seed)

    rows = []
    for i in range(n):
        city = rng.choice(CITIES, p=_city_weights())
        locality = rng.choice(LOCALITIES[city])
        ptype = rng.choice(PROPERTY_TYPES, p=[0.55, 0.2, 0.1, 0.15])
        bhk = int(rng.choice([1, 2, 3, 4, 5], p=[0.15, 0.35, 0.3, 0.15, 0.05]))
        # Area correlates with BHK
        base_area = {1: 480, 2: 750, 3: 1080, 4: 1550, 5: 2200}[bhk]
        area = max(280, rng.normal(base_area, base_area * 0.15))
        bedrooms = bhk
        bathrooms = max(1, min(bhk + 1, int(rng.normal(bhk, 0.6))))
        age = max(0, int(rng.exponential(6)))
        floor = int(rng.integers(0, 25))
        total_floors = max(floor + 1, int(rng.integers(3, 30)))
        furnishing = rng.choice(FURNISHING, p=[0.45, 0.35, 0.2])
        parking = int(rng.choice([0, 1, 2], p=[0.25, 0.55, 0.2]))
        amenities = _sample_amenities(rng)

        base_psf = CITY_BASE_PSF[city]
        # Locality noise (+/- 20%)
        locality_mult = rng.normal(1.0, 0.12)
        # Age depreciation (up to ~25% by 25 yrs)
        age_mult = max(0.7, 1 - 0.01 * age)
        # Floor premium (higher floors slightly pricier, ground floor slight discount)
        floor_mult = 1 + 0.003 * min(floor, 20) - (0.02 if floor == 0 else 0)
        # Furnishing premium
        furnishing_mult = {"Unfurnished": 1.0, "Semi-Furnished": 1.05, "Furnished": 1.12}[furnishing]
        # Amenities premium
        amenity_mult = 1 + 0.01 * len(amenities)
        # Property type premium
        type_mult = {"Apartment": 1.0, "Independent House": 1.06, "Row House": 1.1, "Villa": 1.25}[ptype]
        # BHK premium (bigger configs command a small psf premium in prime cities)
        bhk_mult = 1 + 0.01 * max(0, bhk - 2)

        psf = (
            base_psf
            * locality_mult
            * age_mult
            * floor_mult
            * furnishing_mult
            * amenity_mult
            * type_mult
            * bhk_mult
        )
        psf = max(1500, psf)
        fair_price = psf * area  # "true" underlying fair value

        # Listed price: sellers deviate from fair value by a noisy margin
        listing_noise = rng.normal(1.0, 0.08)
        listed_price = fair_price * listing_noise

        rows.append(
            {
                "id": f"PI-{i+1:05d}",
                "city": city,
                "locality": locality,
                "property_type": ptype,
                "bhk": bhk,
                "area_sqft": round(area, 1),
                "bedrooms": bedrooms,
                "bathrooms": bathrooms,
                "age_years": age,
                "floor": floor,
                "total_floors": total_floors,
                "furnishing": furnishing,
                "parking": parking,
                "amenities": ", ".join(amenities),
                "amenities_count": len(amenities),
                "fair_price": round(fair_price, 0),
                "listed_price": round(listed_price, 0),
                "price_per_sqft": round(psf, 0),
            }
        )

    df = pd.DataFrame(rows)
    return df


def _city_weights():
    # Weight larger metros higher so the dataset skews realistic
    w = {
        "Mumbai": 0.24,
        "Pune": 0.22,
        "Nagpur": 0.14,
        "Nashik": 0.14,
        "Kolhapur": 0.10,
        "Satara": 0.08,
        "Sangli": 0.08,
    }
    return [w[c] for c in CITIES]


if __name__ == "__main__":
    df = generate_dataset()
    df.to_csv("maharashtra_housing.csv", index=False)
    print(df.head())
    print(f"\nGenerated {len(df)} rows -> maharashtra_housing.csv")
