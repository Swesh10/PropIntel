# PropIntel

**Maharashtra AI-Powered Property Price Prediction & Insight Platform**

A full-stack ML web application: a FastAPI + scikit-learn/XGBoost backend serving
price predictions, SHAP explanations, what-if sensitivity analysis, comparisons and
recommendations, paired with a React + Tailwind dashboard (Dashboard, Mumbai Listings,
Price Prediction, Explainable AI, What-If Analysis, and Recommendations).

```
propintel/
├── backend/
│   ├── data_gen.py      # Synthetic Maharashtra housing dataset generator
│   ├── ml_engine.py      # PropIntelPredictor, XAIExplainer, WhatIfEngine, RecommendationEngine
│   ├── app.py             # FastAPI app + REST endpoints
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── components/    # Sidebar, Dashboard, PricePrediction, CompareProperties,
    │   │                  # ExplainableAI, WhatIfAnalysis, Recommendations, Shared
    │   ├── api.js          # REST client
    │   ├── report.js       # Client-side PDF report generator (jsPDF)
    │   ├── App.jsx / main.jsx / index.css
    ├── index.html
    ├── tailwind.config.js
    ├── vite.config.js
    └── package.json
```

## 1. Architecture

- **Backend:** FastAPI (Python). Serves the regression model selected from the
  cleaned Mumbai listings dataset, with one shared `ColumnTransformer`
  preprocessing pipeline (`OneHotEncoder` for categoricals, `StandardScaler`
  for numerics).
  If the saved artifact is missing or stale, startup compares Linear Regression,
  Random Forest, Gradient Boosting, and XGBoost using five-fold cross-validation
  on total-price and price-per-square-foot targets, including log1p variants for
  tree ensembles. Targets are inverse-transformed before metrics and predictions;
  per-square-foot outputs are multiplied by area to recover INR. The selected
  model and target transform are saved together. Version 5 uses group-aware
  holdout and cross-validation splits so identical property inputs cannot appear
  in both training and evaluation partitions.
- **XAI:** `shap.PermutationExplainer` attributes the complete prediction function
  in INR, including target inverse transforms and the area multiplier. It reports
  a sampled-training-background base value, additive per-feature impacts, top
  positive/negative drivers, and the lowest-impact features. Contributions are
  associations learned from asking-price data, not causal effects. Reliability
  is reported through training-range and locality-support warnings, not a
  probability or calibrated confidence score.
- **What-If Engine:** re-runs inference on a modified copy of a base property to
  compute an instant price delta.
- **Recommendation Engine:** rule-based scoring blending budget fit, value-for-money
  (model-estimated value vs listed price), and preference match (city/BHK/type/
  furnishing). It uses cached model predictions; the "Below AI estimate" badge
  appears only when the estimate passes the existing reliability checks and is
  materially above the listed price. Its fit score is a relative ranking, not a
  probability.
- **Frontend:** React 18 + Tailwind CSS + Recharts + lucide-react, matching the
  PropIntel brand (`#0F172A` navy sidebar, `#F8FAFC` surface), with a client-side
  PDF report generator (`Report.generatePDF()`, via jsPDF).

## 2. Backend setup

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt

uvicorn app:app --reload --port 8000
```

PowerShell on Windows:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

### MongoDB Atlas (optional prediction history)

The ML dataset and model remain local and are not imported into MongoDB. Atlas
stores registered users and prediction history. Create `backend/.env` from the
placeholder file and enter the Atlas connection URI locally; never paste
credentials into source code or commit the `.env` file:

```powershell
cd backend
Copy-Item .env.example .env
notepad .env
python -m pip install -r requirements.txt
```

Set `MONGODB_URI` to your rotated Atlas URI and leave `MONGODB_DB_NAME=propintel`.
In Atlas, allow the server's IP address in Network Access and ensure the database
user has appropriate access. Restart the backend, then check
`http://localhost:8000/api/health`. The database status is `connected`,
`not_configured`, or `unavailable`; overall health is `degraded` unless both
the model and database are ready. Health responses never include the URI.
The health response also includes a safe diagnostic message for invalid URI,
authentication, network, or DNS-related failures without showing connection
details.
The backend can still serve the existing ML features if MongoDB is not
configured, while history requests report a clear error.

Registration creates the account and signs the user in immediately; email
verification is not required. Password reset links are sent by email, so
configure `SMTP_HOST`, `SMTP_PORT`, and `EMAIL_FROM`; set `SMTP_USERNAME` and
`SMTP_PASSWORD` together when the mail provider requires authentication.
Existing PBKDF2 password hashes are verified and upgraded to Argon2id after a
successful login. New access tokens are short-lived and held in frontend
memory; rotating refresh tokens are stored as hashes in MongoDB and sent only
in HttpOnly cookies. Prediction history remains scoped to the authenticated
user's email.

For production, set `PROPINTEL_ENV=production` and configure `JWT_SECRET_KEY`
with at least 32 bytes of random data. Generate a value locally in PowerShell
with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`PROPINTEL_AUTH_SECRET` remains a supported legacy secret name. The local
development secret and demo administrator credentials are not used in
production. Production admin login is disabled unless both
`PROPINTEL_ADMIN_EMAIL` and `PROPINTEL_ADMIN_PASSWORD` are explicitly set;
configured admin passwords must be at least 12 characters. Set
`PROPINTEL_ALLOWED_ORIGINS` to a comma-separated list of exact trusted frontend
origins (scheme and hostname, no path); do not use `*` with credentialed CORS.
Set `FRONTEND_BASE_URL` to the public frontend origin so password-reset links
are generated for the correct site.

The refresh-cookie flow uses secure, cross-site cookies in production. Browsers
may block third-party cookies when the frontend and API are on unrelated sites;
use same-site custom domains or a same-site proxy if refresh-session restoration
does not work in the deployed browser. Authentication persistence and password
reset use MongoDB transactions, so use a replica-set deployment such as MongoDB
Atlas.

On startup the server loads the cleaned Mumbai catalog and validated
`mumbai_model_v5.joblib`. It does not retrain or overwrite an artifact during
startup. If the active artifact is missing or incompatible, the model service
remains unavailable until an offline candidate is evaluated. To train a
separate candidate, run `python train_mumbai_model.py` from `backend`; the
script writes `models/mumbai_model_candidate.joblib`, leaving the active model
untouched. Review its grouped cross-validation and held-out MAE, RMSE, R², and
MAPE metrics before any deliberate promotion. Version 5 uses group-aware
holdout and cross-validation splits so identical property inputs cannot appear
in both training and evaluation partitions.

| Method | Endpoint              | Purpose                                             |
|--------|------------------------|------------------------------------------------------|
| GET    | `/api/meta`            | Cities, localities, property types, amenities, stats |
| POST   | `/api/predict`         | Predict fair price + SHAP explanation for a property |
| POST   | `/api/prediction-history` | Calculate and save a prediction to MongoDB history |
| GET    | `/api/prediction-history` | Retrieve the authenticated user's history      |
| GET    | `/api/health`          | Model and MongoDB dependency status                    |
| POST   | `/api/what-if`         | Recompute price for a modified property (sensitivity) |
| GET    | `/api/compare`         | Listings-page data with AI estimates + variance       |
| POST   | `/api/recommend`       | Budget-bounded, match-scored property recommendations |
| GET    | `/api/market-trends`   | Current listing-price averages and catalog counts      |

Interactive API docs are available at `http://localhost:8000/docs`.

To generate a separate synthetic demo CSV (not used by the active Mumbai model):

```bash
python data_gen.py   # writes maharashtra_housing.csv
```

## 3. Frontend setup

```bash
cd frontend
npm install
npm run dev      # starts Vite dev server on http://localhost:5173
```

The Vite dev server proxies `/api/*` requests to `http://localhost:8000`
(see `vite.config.js`), so run the backend first. For another API origin, set
`VITE_API_BASE_URL` to the full API prefix, such as
`https://api.example.com/api` (see `frontend/.env.example`).

For a production build:

```bash
npm run build     # outputs to frontend/dist
npm run preview   # serve the production build locally
```

### Deployment preparation

The backend binds to `0.0.0.0` in production and uses the platform-provided
`PORT` (default 8000). Set backend environment variables through the hosting
platform's secret/configuration settings; do not deploy `.env` files. Set
`PROPINTEL_ENV=production`, `PROPINTEL_AUTH_SECRET`, `MONGODB_URI`,
`MONGODB_DB_NAME`, and any cross-origin frontend origin. Set frontend
`VITE_API_BASE_URL` to the deployed API prefix before building the frontend.
The frontend build is static (`frontend/dist`); serve it through a static host
or a configured web server with SPA route fallback. This repository has not
been deployed to Azure, and a production deployment still requires configuring
the hosting services, TLS/custom domains, Atlas network access, and secrets.

## 4. Notes on the dataset

The Mumbai model uses the bundled listing dataset. Prices (including ranges
with lakh/crore units on either endpoint) are normalized to INR, and ranges use
their lower endpoint; areas are parsed into square feet. Non-sale records and
implausible price-per-square-foot outliers are excluded by the same cleaner
used for both training and API catalog results. The cleaner also applies the
existing ₹20 Cr upper-price limit and trims the outer 1% of area values after
the other filters; its logs report those removal counts separately. The target
is the listing's asking price, not a verified transaction price or independent
appraisal.
The cleaner retains the source `VERIFIED` flag for catalog presentation; listings
not marked verified are identified as such and are not represented as confirmed
sale records. Recommendation estimates are generated with five-fold, grouped
cross-validation so each listing is excluded from the model fold used to
estimate it. Ranking prioritizes a smaller absolute estimate-to-listing
difference as a percentage of the listed price, then uses source verification,
model reliability, and the existing preference match score to break ties.
Price-agreement labels use the held-out MAPE as a comparison reference only;
they are not confidence guarantees or sale-price validation.
Only property types represented by usable training categories (Apartment,
Studio Apartment, and Villa) are retained; unsupported categories are not
silently relabeled as apartments. Studio Apartment and Villa have limited
training examples and receive a support warning. Bedrooms duplicate BHK in the
source data, while bathroom and parking values are unavailable or synthetic,
so those fields are excluded from the model and disclosed as estimate
limitations. Positive parking values are flagged as unsupported.
Consequently, the model estimates
the price pattern in this dataset and should not be treated as a definitive
fair-market valuation until it is retrained and validated against verified
closed-sale data. Estimates with sparse locality support or features outside
commonly seen training ranges are flagged in the API and comparison UI.

## 5. Extending

- Swap `RandomForestRegressor` / `XGBRegressor` for another estimator in
  `PropIntelPredictor._build_model()` — the model-agnostic Permutation SHAP wrapper
  explains the complete INR inference function.
- Persist the trained model with `joblib.dump` to avoid retraining on every
  restart in production.
- Move the in-memory catalog (`STATE["catalog"]`) to PostgreSQL/SQLite for a
  real deployment; the `RecommendationEngine`/`compare` endpoint logic is
  DataFrame-based and ports directly to a SQL-backed query layer.
