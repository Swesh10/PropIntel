import React, { useEffect, useMemo, useState } from "react";
import { ArrowRight, RotateCcw, SlidersHorizontal } from "lucide-react";
import { Card, SectionHeader, formatINR, formatPSF, Spinner } from "./Shared.jsx";
import { api } from "../api.js";

const toWhatIfFurnishing = (value) =>
  value && value !== "Unfurnished" ? "Semi-Furnished" : "Unfurnished";

const getWhatIfFurnishingLabel = (value) =>
  toWhatIfFurnishing(value) === "Unfurnished" ? "Unfurnished" : "Furnished";

export default function WhatIfAnalysis({ meta, initialPrediction, onNavigateToPredict }) {
  // Guard: if no prediction has been run yet, do NOT auto-predict with a
  // hardcoded property (that city may not exist in the loaded model). Instead
  // show a clear CTA directing the user to run a prediction first.
  if (!initialPrediction) {
    return (
      <div>
        <SectionHeader
          title="What-If Analysis"
          subtitle="Adjust property parameters and see the listing-price estimate update in real time."
        />
        <Card className="flex flex-col items-center justify-center gap-5 p-12 text-center">
          <div className="w-16 h-16 rounded-2xl bg-amber-50 flex items-center justify-center">
            <SlidersHorizontal size={28} className="text-accent-amber" />
          </div>
          <div>
            <p className="font-display text-xl font-bold text-ink-900">No prediction to analyse yet</p>
            <p className="text-sm text-ink-600 mt-2 max-w-sm">
              Run a price prediction first — then click <strong>"Run what-if"</strong> on the result
              to open this tool pre-loaded with that property.
            </p>
          </div>
          {onNavigateToPredict && (
            <button onClick={onNavigateToPredict} className="button-primary">
              Go to Price Prediction <ArrowRight size={16} />
            </button>
          )}
        </Card>
      </div>
    );
  }

  return <WhatIfContent meta={meta} initialPrediction={initialPrediction} />;
}

function WhatIfContent({ meta, initialPrediction }) {
  const base = useMemo(() => initialPrediction.input, [initialPrediction]);
  const basePrice = initialPrediction.prediction?.predicted_price;
  const localities = useMemo(() => {
    const cityLocalities = meta?.localities_by_city?.[base.city] || [];
    return cityLocalities.includes(base.locality)
      ? cityLocalities
      : [base.locality, ...cityLocalities];
  }, [base.city, base.locality, meta]);

  const [area, setArea] = useState(base.area_sqft);
  const [bhk, setBhk] = useState(base.bhk);
  const [furnishing, setFurnishing] = useState(
    toWhatIfFurnishing(base.furnishing || "Unfurnished")
  );
  const [locality, setLocality] = useState(base.locality);

  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const changes = useMemo(
    () => ({
      area_sqft: area,
      bhk,
      bedrooms: bhk,
      furnishing,
      locality,
    }),
    [area, bhk, furnishing, locality]
  );

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    const t = setTimeout(() => {
      api
        .whatIf(base, changes)
        .then((res) => active && setResult(res))
        .catch((loadError) => active && setError(loadError.message))
        .finally(() => active && setLoading(false));
    }, 250);
    return () => {
      active = false;
      clearTimeout(t);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [changes]);

  const reset = () => {
    setArea(base.area_sqft);
    setBhk(base.bhk);
    setFurnishing(toWhatIfFurnishing(base.furnishing || "Unfurnished"));
    setLocality(base.locality);
  };
  const displayedBasePrice = result
    ? Number.isFinite(basePrice)
      ? Number(basePrice)
      : result.base_price
    : null;
  const priceImpact = result ? result.new_price - displayedBasePrice : 0;
  const percentageChange = displayedBasePrice
    ? (priceImpact / displayedBasePrice) * 100
    : 0;
  const positiveImpact = priceImpact >= 0;

  return (
    <div>
      <SectionHeader
        title="What-If Analysis"
        subtitle="Adjust property parameters and see the listing-price estimate update in real time."
        right={
          <button
            onClick={reset}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-ink-600 border border-slate-200 rounded-lg px-3 py-2 hover:border-slate-300"
          >
            <RotateCcw size={13} /> Reset to base
          </button>
        }
      />

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Base panel */}
        <Card className="col-span-1 min-w-0 p-4 sm:p-6 lg:col-span-2">
          <p className="text-xs font-semibold text-ink-400 uppercase tracking-wide mb-3">Base Property</p>
          <p className="font-display text-lg font-bold text-ink-900">
            {base.bhk} BHK {base.property_type}
          </p>
          <p className="text-sm text-ink-600">{base.locality}, {base.city}</p>
          <div className="grid grid-cols-2 gap-3 mt-4 text-sm">
            <InfoRow label="Area" value={`${base.area_sqft} sq.ft`} />
            <InfoRow label="Floor" value={base.floor} />
            <InfoRow label="Age" value={`${base.age_years} yrs`} />
            <InfoRow
              label="Furnishing"
              value={getWhatIfFurnishingLabel(base.furnishing)}
            />
          </div>
        </Card>

        {/* Sliders */}
        <Card className="col-span-1 min-w-0 p-4 sm:p-6 lg:col-span-3">
          <p className="text-xs font-semibold text-ink-400 uppercase tracking-wide mb-4">Adjust Parameters</p>
          <div className="space-y-5">
            <SliderField label={`Area — ${area} sq.ft`} min={280} max={4500} step={10} value={area} onChange={setArea} />
            <SliderField label={`BHK Configuration — ${bhk} BHK`} min={1} max={5} step={1} value={bhk} onChange={setBhk} />
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <label className="block">
                <span className="mb-2 block text-xs font-medium text-ink-600">Furnishing Status</span>
                <select
                  className="input"
                  value={furnishing}
                  onChange={(event) => setFurnishing(event.target.value)}
                >
                  <option value="Unfurnished">Unfurnished</option>
                  <option value="Semi-Furnished">Furnished</option>
                </select>
                <span className="mt-1 block text-xs leading-5 text-ink-400">
                  Model estimates reflect historical listings; more furnishing does not guarantee a higher estimate.
                </span>
              </label>
              <label className="block">
                <span className="mb-2 block text-xs font-medium text-ink-600">Locality</span>
                <select
                  className="input"
                  value={locality}
                  onChange={(event) => setLocality(event.target.value)}
                  disabled={!localities.length}
                >
                  {localities.map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </select>
                <span className="mt-1 block text-xs leading-5 text-ink-400">
                  Localities available for {base.city} in the training catalog.
                </span>
              </label>
            </div>
          </div>
        </Card>
      </div>

      {/* Delta result */}
      <Card className="p-6 mt-6">
        {error ? (
          <div role="alert" className="error-banner">
            {error}
            {error.toLowerCase().includes("authentication") &&
              " Sign in from the top-right, then adjust a parameter to retry."}
          </div>
        ) : loading || !result ? (
          <Spinner label="Recalculating…" />
        ) : (
          <div className="flex items-center justify-center gap-6 flex-wrap">
            <div className="text-center">
              <p className="text-xs text-ink-400 uppercase tracking-wide">Base Estimate</p>
              <p className="font-display text-2xl font-bold text-ink-900 mt-1">{formatINR(displayedBasePrice)}</p>
              <p className="text-xs text-ink-400 mt-0.5">{formatPSF(initialPrediction.prediction?.predicted_price_per_sqft ?? result.base_price_per_sqft)}</p>
            </div>
            <ArrowRight size={22} className="text-slate-300" />
            <div className="text-center">
              <p className="text-xs text-ink-400 uppercase tracking-wide">Adjusted Estimate</p>
              <p className="font-display text-2xl font-bold text-accent-teal mt-1">{formatINR(result.new_price)}</p>
              <p className="text-xs text-ink-400 mt-0.5">{formatPSF(result.new_price_per_sqft)}</p>
            </div>
            <div
              className={`rounded-xl px-4 py-3 text-center ${
                positiveImpact ? "bg-teal-50 text-accent-teal" : "bg-rose-50 text-accent-coral"
              }`}
            >
              <p className="text-xs font-medium uppercase tracking-wide">Price Impact</p>
              <p className="mt-1 text-sm font-semibold">
                {positiveImpact ? "+" : "-"}{formatINR(Math.abs(priceImpact))}
              </p>
              <p className="mt-2 text-xs font-medium uppercase tracking-wide">Percentage Change</p>
              <p className="mt-1 text-sm font-semibold">
                {positiveImpact ? "+" : "-"}{Math.abs(percentageChange).toFixed(2)}%
              </p>
            </div>
          </div>
        )}
        {!error && !loading && result && (
          <p className="mt-4 text-center text-xs leading-5 text-ink-400">
            Estimates come directly from the trained model. Small changes can sometimes produce the same estimate.
          </p>
        )}
      </Card>
    </div>
  );
}

function InfoRow({ label, value }) {
  return (
    <div>
      <p className="text-xs text-ink-400">{label}</p>
      <p className="font-medium text-ink-900">{value}</p>
    </div>
  );
}

function SliderField({ label, min, max, step, value, onChange }) {
  return (
    <label className="block">
      <span className="block text-xs font-medium text-ink-600 mb-2">{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full slider-thumb"
      />
    </label>
  );
}
