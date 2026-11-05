import React, { useEffect, useState } from "react";
import { BarChart3, FileDown } from "lucide-react";
import { Card, SectionHeader, Spinner, formatINR, formatPSF } from "./Shared.jsx";
import { api } from "../api.js";

export default function Recommendations({ meta, user }) {
  const validationMape = meta?.model_metrics?.mape;
  const [prefs, setPrefs] = useState({ city: "", bhk: 2, budget_min: 2000000, budget_max: 9000000 });
  const [results, setResults] = useState([]);
  const [matchingCount, setMatchingCount] = useState(null);
  const [loading, setLoading] = useState(false);
  const [trends, setTrends] = useState(null);
  const [trendsError, setTrendsError] = useState("");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const displayedResults = results;
  const budgetRangeError = prefs.budget_min < 0 || prefs.budget_max < 0
    ? "Budgets cannot be negative."
    : prefs.budget_min > prefs.budget_max
      ? "Minimum Budget cannot exceed Maximum Budget."
      : "";

  const loadRecs = async () => {
    if (budgetRangeError) {
      setError("");
      return;
    }
    if (!user) {
      setResults([]);
      setMatchingCount(0);
      setError("");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await api.recommend({ ...prefs, top_n: 6 });
      setResults(res.results);
      setMatchingCount(res.count);
    } catch (loadError) {
      setError(loadError.message || "Unable to load recommendations.");
    } finally {
      setLoading(false);
    }
  };

  const setMinimumBudget = (value) => {
    setPrefs((current) => ({
      ...current,
      budget_min: value,
    }));
  };

  const setMaximumBudget = (value) => {
    setPrefs((current) => ({
      ...current,
      budget_max: value,
    }));
  };

  useEffect(() => {
    if (user) {
      loadRecs();
    } else {
      setResults([]);
      setMatchingCount(0);
      setError("");
      setLoading(false);
    }
    // Load on authentication changes; filters are applied explicitly by the user.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  useEffect(() => {
    setTrends(null);
    setTrendsError("");
    let active = true;
    api.marketTrends(prefs.city)
      .then((data) => { if (active) setTrends(data); })
      .catch((loadError) => { if (active) setTrendsError(loadError.message); });
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefs.city]);

  const handleGenerateReport = async () => {
    setGenerating(true);
    setError("");
    try {
      const { Report } = await import("../report.js");
    await Report.generatePDF({
      prefs,
      results: displayedResults,
      trends,
      city: prefs.city,
    });
    } catch (pdfError) {
      // Surface the error clearly — previously this was silently swallowed.
      setError(`PDF generation failed: ${pdfError.message || "Unknown error"}. Please try again.`);
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div>
      <SectionHeader
        title="Recommendations & Market Snapshot"
        subtitle="Personalised matches beside current listings. Fit scores are relative rankings, not probabilities."
        right={
          <button
            onClick={handleGenerateReport}
            disabled={generating}
            className="inline-flex items-center gap-2 bg-accent-teal text-white text-sm font-semibold px-4 py-2.5 rounded-lg hover:bg-teal-700 transition-colors disabled:opacity-60"
          >
            <FileDown size={15} />
            {generating ? "Generating…" : "Download PDF Report"}
          </button>
        }
      />
      {Number.isFinite(validationMape) && (
        <p className="mb-4 text-xs leading-5 text-ink-400">
          On held-out data, the model&apos;s average percentage error was {validationMape.toFixed(1)}%; individual estimates can differ more.
        </p>
      )}

      <Card className="mb-5 rounded-xl p-5 sm:p-6">
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4 lg:items-end">
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1.5">City</span>
            <select
              className="input"
              value={prefs.city}
              onChange={(e) => setPrefs((p) => ({ ...p, city: e.target.value }))}
            >
              <option value="">All zones</option>
              {(meta?.cities || []).map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="block text-xs font-medium text-ink-600 mb-1.5">BHK</span>
            <select
              className="input"
              value={prefs.bhk}
              onChange={(e) => setPrefs((p) => ({ ...p, bhk: Number(e.target.value) }))}
            >
              {[1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>{n} BHK</option>
              ))}
            </select>
          </label>
          <button
            onClick={loadRecs}
            disabled={!user || loading}
            className="rounded-lg bg-accent-teal py-2.5 text-sm font-semibold text-white transition-colors hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? "Applying…" : user ? "Apply Filters" : "Sign in to apply filters"}
          </button>
        </div>
        <div className="mt-5 grid grid-cols-1 gap-5 border-t border-slate-100 pt-5 sm:grid-cols-2">
          <label className="block rounded-xl bg-slate-50 p-4">
            <span className="flex items-center justify-between gap-3 text-xs font-medium text-ink-600">
              <span>Minimum Budget</span>
              <span className="font-semibold text-ink-900">{formatINR(prefs.budget_min)}</span>
            </span>
            <input
              aria-label="Minimum Budget"
              type="range"
              min={0}
              max={50000000}
              step={500000}
              value={prefs.budget_min}
              onChange={(e) => setMinimumBudget(Number(e.target.value))}
              className="mt-3 w-full slider-thumb"
            />
            <span className="mt-1 flex justify-between text-[10px] text-ink-400">
              <span>{formatINR(0)}</span>
              <span>{formatINR(50000000)}</span>
            </span>
          </label>
          <label className="block rounded-xl bg-slate-50 p-4">
            <span className="flex items-center justify-between gap-3 text-xs font-medium text-ink-600">
              <span>Maximum Budget</span>
              <span className="font-semibold text-ink-900">{formatINR(prefs.budget_max)}</span>
            </span>
            <input
              aria-label="Maximum Budget"
              type="range"
              min={0}
              max={50000000}
              step={500000}
              value={prefs.budget_max}
              onChange={(e) => setMaximumBudget(Number(e.target.value))}
              className="mt-3 w-full slider-thumb"
            />
            <span className="mt-1 flex justify-between text-[10px] text-ink-400">
              <span>{formatINR(prefs.budget_min)}</span>
              <span>{formatINR(50000000)}</span>
            </span>
          </label>
        </div>
        {budgetRangeError && (
          <p role="alert" className="mt-3 text-sm text-red-700">
            {budgetRangeError} Adjust the range before applying filters.
          </p>
        )}
      </Card>

      {error && <div role="alert" className="error-banner mb-5">{error}{error.toLowerCase().includes("authentication") && " Sign in from the top-right to see recommendations."}</div>}
      {trendsError && <div role="alert" className="error-banner mb-5">Market snapshot unavailable: {trendsError}</div>}

      <Card className="mb-5 flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
        <div>
          <p className="text-sm font-semibold text-ink-900">Recommendation Catalog</p>
          <p className="mt-1 text-xs leading-5 text-ink-500">
            Listed prices are source listing asking prices, not confirmed sale prices. AI estimates are generated without training on that same listing and are not verified market values.
          </p>
        </div>
        <div className="shrink-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-ink-600">
          Catalog
        </div>
      </Card>

      {Number.isFinite(validationMape) && validationMape > 0 && (
        <p className="mb-4 text-xs leading-5 text-ink-400">
          Price agreement compares the price gap with held-out model error: Close is within {validationMape.toFixed(1)}% (average validation error), Moderate is up to {(validationMape * 2).toFixed(1)}%, and Large is above that. These labels are comparisons, not confidence guarantees.
        </p>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5 mb-6">
        {/* Recommendations grid */}
        <div className="col-span-1 grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2 lg:col-span-3">
          {!loading && user && matchingCount !== null && matchingCount > 0 && (
            <p className="col-span-1 text-sm text-ink-600 sm:col-span-2" aria-live="polite">
              Showing {displayedResults.length} of {matchingCount.toLocaleString("en-IN")} properties matching your filters.
            </p>
          )}
          {loading ? (
            <div className="col-span-1 sm:col-span-2"><Spinner label="Finding your best matches…" /></div>
          ) : (
            displayedResults.map((r) => {
              const listedPrice = Number(r.listed_price);
              const priceDifference = Number.isFinite(Number(listedPrice))
                && Number.isFinite(Number(r.fair_price))
                ? Math.abs(Number(listedPrice) - Number(r.fair_price))
                : null;
              const agreementStatus = {
                close: {
                  label: "Close price match",
                  className: "border-emerald-200 bg-emerald-50 text-emerald-800",
                },
                moderate: {
                  label: "Moderate price difference",
                  className: "border-amber-200 bg-amber-50 text-amber-800",
                },
                large: {
                  label: "Large price difference",
                  className: "border-rose-200 bg-rose-50 text-rose-800",
                },
              }[r.price_agreement];
              return (
              <Card key={r.id} className="p-5">
                <div className="flex min-w-0 items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="break-words font-semibold leading-5 text-ink-900">{r.bhk} BHK {r.property_type}</p>
                    <p className="break-words text-xs leading-5 text-ink-400">{r.locality}, {r.city}</p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="font-display text-lg font-bold text-accent-teal">{r.match_score}%</p>
                    <p className="text-[10px] font-semibold uppercase tracking-wide text-ink-500">Match Score</p>
                  </div>
                </div>
                <p className="mt-2 text-xs leading-5 text-ink-400">
                  {Number(r.area_sqft).toLocaleString("en-IN")} sq.ft · How closely this property matches your search preferences.
                </p>
                <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="min-w-0 rounded-lg border border-slate-200 bg-slate-50 p-3">
                    <p className="text-xs font-medium text-ink-500">
                      Listed Price
                    </p>
                    <p className="mt-1 break-words font-display text-lg font-bold text-ink-900">{formatINR(listedPrice)}</p>
                    <p className="mt-1 text-[11px] leading-4 text-ink-400">
                      Asking price; not a confirmed sale price
                    </p>
                  </div>
                  <div className="min-w-0 rounded-lg border border-navy-100 bg-navy-50 p-3">
                    <p className="text-xs font-medium text-ink-500">AI Estimated Price</p>
                    <p className="mt-1 break-words font-display text-lg font-bold text-navy-950">{formatINR(r.fair_price)}</p>
                    <p className="mt-1 text-[11px] leading-4 text-ink-400">Estimated without training on this listing</p>
                  </div>
                </div>
                <p className="mt-3 text-xs font-medium text-ink-600">
                  Price Difference: {formatINR(priceDifference)}
                  {priceDifference === null
                    ? ""
                    : listedPrice > r.fair_price
                      ? " above model prediction"
                      : listedPrice < r.fair_price
                        ? " below model prediction"
                        : " (same as model prediction)"}
                  {Number.isFinite(r.price_difference_pct) && ` · ${r.price_difference_pct.toFixed(1)}%`}
                </p>
                <div className="mt-4 flex flex-wrap items-center gap-2">
                  {agreementStatus && (
                    <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${agreementStatus.className}`}>
                      {agreementStatus.label}
                    </span>
                  )}
                  <span className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${
                    r.source_verified
                      ? "border-sky-200 bg-sky-50 text-sky-800"
                      : "border-slate-200 bg-slate-50 text-ink-600"
                  }`}>
                    {r.source_verified ? "Source marked verified" : "Source not marked verified"}
                  </span>
                  <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-ink-600">
                    Model Prediction – Experimental
                  </span>
                  {(() => {
                    const warnings = Array.isArray(r.reliability_warnings)
                      ? r.reliability_warnings
                      : Array.isArray(r.warnings)
                        ? r.warnings
                        : [];
                    const lowReliability = r.is_reliable === false || warnings.length > 0;
                    return (
                      <span
                        title={warnings.length ? warnings.join(" ") : undefined}
                        className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${
                          lowReliability
                            ? "border-amber-200 bg-amber-50 text-amber-800"
                            : "border-slate-200 bg-white text-ink-600"
                        }`}
                      >
                        {lowReliability
                          ? "Low Prediction Reliability – Verify This Estimate"
                          : "Model Prediction Available"}
                      </span>
                    );
                  })()}
                </div>
                {Array.isArray(r.reliability_warnings) && r.reliability_warnings.length > 0 && (
                  <p className="mt-2 text-xs leading-5 text-amber-800">
                    {r.reliability_warnings.join(" ")}
                  </p>
                )}
              </Card>
              );
            })
          )}
          {!user && (
            <p className="col-span-1 py-10 text-center text-sm text-ink-400 sm:col-span-2">Sign in to see recommendations for your preferences.</p>
          )}
          {!loading && user && results.length === 0 && (
            <p className="col-span-1 py-10 text-center text-sm text-ink-400 sm:col-span-2">
              No properties found in this budget range. Try adjusting your budget or other filters.
            </p>
          )}
        </div>

        {/* Current catalog snapshot */}
        <Card className="col-span-1 min-w-0 p-4 sm:p-6 lg:col-span-2">
          <div className="flex items-center gap-2 mb-1">
            <BarChart3 size={16} className="text-accent-teal" />
            <p className="text-sm font-semibold text-ink-900">Catalog snapshot</p>
          </div>
          {!trends ? (
            <Spinner />
          ) : (
            <>
              <p className="mb-4 text-xs text-ink-400">
                Descriptive figures from current cleaned listings, not a future price prediction.
              </p>
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg bg-slate-50 p-3">
                  <p className="text-xs text-ink-400">Listings in catalog</p>
                  <p className="mt-1 text-lg font-bold text-ink-900">{trends.total_properties.toLocaleString("en-IN")}</p>
                </div>
                <div className="rounded-lg bg-slate-50 p-3">
                  <p className="text-xs text-ink-400">Average asking price / sq.ft</p>
                  <p className="mt-1 text-lg font-bold text-ink-900">{formatPSF(trends.average_price_per_sqft)}</p>
                </div>
              </div>
              <p className="mt-4 text-xs text-ink-500">
                {Object.entries(trends.bhk_distribution || {})
                  .map(([bhk, count]) => `${bhk} BHK: ${count.toLocaleString("en-IN")}`)
                  .join(" · ") || "No listings are available for this selection."}
              </p>
            </>
          )}
        </Card>
      </div>

      <Card className="p-5 sm:p-6">
        <h2 className="font-display text-lg font-bold text-navy-950">
          Understanding AI Property Predictions
        </h2>
        <p className="mt-2 text-sm leading-6 text-ink-600">
          PropIntel uses a machine learning model trained on historical property listing data to estimate property prices based on property characteristics and location. The AI Predicted Price represents the model&apos;s estimated value, while the Listed Price represents the seller&apos;s asking price.
        </p>
        <p className="mt-3 border-t border-slate-100 pt-3 text-xs leading-5 text-ink-400">
          These predictions are experimental and may differ from actual market prices depending on data availability and model accuracy. Always verify property details and market prices before making decisions.
        </p>
      </Card>
    </div>
  );
}
