import React, { useMemo, useState } from "react";
import { Brain, Loader2, Minus, SlidersHorizontal, Sparkles, TrendingDown, TrendingUp } from "lucide-react";
import { api } from "../api.js";
import { Badge, Card, SectionHeader, formatINR, formatPSF } from "./Shared.jsx";

const DEFAULT_FORM = { city: "", locality: "", property_type: "Apartment", bhk: 2, area_sqft: 850, bedrooms: 2, bathrooms: 2, age_years: 3, floor: 5, furnishing: "Furnished", parking: 0, amenities: ["Lift", "Parking", "Security"], listed_price: "" };

const normalizeLocation = (value) => String(value || "").trim().replace(/\s+/g, " ").toLocaleLowerCase();

function getLocalitiesForCity(meta, city) {
  const cityKey = Object.keys(meta?.localities_by_city || {}).find(
    (key) => normalizeLocation(key) === normalizeLocation(city)
  );
  const localities = cityKey ? meta.localities_by_city[cityKey] : [];
  const uniqueLocalities = new Map();
  for (const locality of localities || []) {
    const key = normalizeLocation(locality);
    if (key && !uniqueLocalities.has(key)) uniqueLocalities.set(key, String(locality).trim());
  }
  return [...uniqueLocalities.values()];
}

export default function PricePrediction({ meta, onExplain, onWhatIf }) {
  const [form, setForm] = useState(DEFAULT_FORM);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const cities = meta?.cities || [];
  const selectedCity = form.city || cities[0] || "";
  const localities = useMemo(() => getLocalitiesForCity(meta, selectedCity), [meta, selectedCity]);
  const propertyTypes = useMemo(() => meta?.property_types || ["Apartment", "Villa"], [meta]);
  const update = (field, value) => setForm((current) => ({ ...current, [field]: value }));
  const toggleAmenity = (amenity) => setForm((current) => ({ ...current, amenities: current.amenities.includes(amenity) ? current.amenities.filter((item) => item !== amenity) : [...current.amenities, amenity] }));

  const submit = async (event) => {
    event.preventDefault(); setLoading(true); setError("");
    const locality = localities.find((option) => normalizeLocation(option) === normalizeLocation(form.locality));
    if (!selectedCity || !locality) {
      setLoading(false);
      setError("Choose a valid locality for the selected market zone.");
      return;
    }
    const payload = { ...form, city: selectedCity, locality, furnishing: form.furnishing === "Furnished" ? "Semi-Furnished" : "Unfurnished", listed_price: form.listed_price !== "" && form.listed_price !== undefined ? Number(form.listed_price) : undefined };
    try {
      try {
        setResult(await api.savePredictionHistory(payload));
      } catch (historyError) {
        setResult(await api.predict(payload));
        setError(`Prediction completed, but saving its history failed or could not be confirmed: ${historyError.message || "Unknown error"}`);
      }
    } catch (submitError) { setError(submitError.message || "Prediction failed."); }
    finally { setLoading(false); }
  };

  const verdictTone = (verdict) => verdict?.includes("Above") ? "negative" : verdict?.includes("Below") ? "positive" : "warning";
  const VerdictIcon = result?.prediction?.delta_pct > 2 ? TrendingUp : result?.prediction?.delta_pct < -2 ? TrendingDown : Minus;

  return <div><SectionHeader title="Price prediction" subtitle="Estimate a price pattern learned from Mumbai listings. This is a listing-price proxy, not a verified sale valuation." /><div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.1fr_0.9fr]">
    <Card className="p-5 sm:p-6"><form onSubmit={submit} className="space-y-5">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2"><Field label="Market zone"><select className="input" value={selectedCity} onChange={(event) => { const city = event.target.value; const nextLocalities = getLocalitiesForCity(meta, city); update("city", city); if (!nextLocalities.some((locality) => normalizeLocation(locality) === normalizeLocation(form.locality))) update("locality", ""); }} required>{cities.map((city) => <option key={city}>{city}</option>)}</select></Field><Field label="Locality"><select className="input" value={form.locality} onChange={(event) => update("locality", event.target.value)} required disabled={!localities.length}><option value="">Choose a locality</option>{localities.map((locality) => <option key={normalizeLocation(locality)} value={locality}>{locality}</option>)}</select></Field></div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2"><Field label="Property type"><select className="input" value={form.property_type} onChange={(event) => update("property_type", event.target.value)}>{propertyTypes.map((type) => <option key={type}>{type}</option>)}</select></Field><Field label="BHK configuration"><div className="flex gap-1.5">{[1, 2, 3, 4, 5].map((number) => <button type="button" key={number} onClick={() => { update("bhk", number); update("bedrooms", number); }} className={`flex-1 rounded-lg border py-2 text-sm font-semibold ${form.bhk === number ? "border-navy-950 bg-navy-950 text-white" : "border-slate-200 bg-white text-ink-600"}`}>{number}</button>)}</div></Field></div>
      <Field label={`Area: ${Math.round(form.area_sqft).toLocaleString("en-IN")} sq.ft`}><input type="range" min="280" max="4500" step="10" value={form.area_sqft} onChange={(event) => update("area_sqft", Number(event.target.value))} className="w-full slider-thumb" /></Field>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3"><Field label="Bathrooms"><input type="number" min="1" max="6" className="input" value={form.bathrooms} onChange={(event) => update("bathrooms", Number(event.target.value))} /><span className="mt-1 block text-xs text-ink-400">Not included in the model estimate.</span></Field><Field label="Furnishing Status"><select className="input" value={form.furnishing} onChange={(event) => update("furnishing", event.target.value)}><option value="Unfurnished">Unfurnished</option><option value="Furnished">Furnished</option></select></Field><Field label="Listed price (optional)"><input type="number" min="0" placeholder="₹ amount" className="input" value={form.listed_price} onChange={(event) => update("listed_price", event.target.value)} /></Field></div>
      <Field label={`Floor — ${form.floor}`}><input type="range" min="0" max="60" step="1" value={form.floor} onChange={(event) => update("floor", Number(event.target.value))} className="w-full slider-thumb" /></Field>
      <Field label="Amenities"><div className="flex flex-wrap gap-2">{(meta?.amenities || ["Lift", "Parking", "Security", "Gym"]).map((amenity) => <button type="button" key={amenity} onClick={() => toggleAmenity(amenity)} className={`rounded-full border px-3 py-1.5 text-xs font-medium ${form.amenities.includes(amenity) ? "border-teal-200 bg-teal-50 text-accent-teal" : "border-slate-200 bg-white text-ink-600"}`}>{amenity}</button>)}</div></Field>
      <button type="submit" disabled={loading} className="button-primary w-full justify-center disabled:cursor-not-allowed disabled:opacity-60">{loading ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}{loading ? "Estimating..." : "Estimate listing price"}</button>
      {error && <div role="alert" className="error-banner">{error}{error.toLowerCase().includes("authentication") && " Sign in from the top-right to run predictions."}</div>}
    </form></Card>
    <div className="space-y-4">
      {!result ? (
        <Card className="flex min-h-[420px] flex-col items-center justify-center p-8 text-center">
          <Sparkles size={30} className="mb-3 text-slate-300" />
          <p className="max-w-xs text-sm leading-6 text-ink-400">
            Your estimate, price-per-square-foot benchmark, and model explanation will appear here.
          </p>
        </Card>
      ) : (
        <>
          <Card className="result-panel p-6 text-white">
            <p className="eyebrow text-teal-200">AI estimated price (listing-price proxy)</p>
            <p className="mt-2 font-display text-4xl font-bold">{formatINR(result.prediction.predicted_price)}</p>
            <p className="mt-1 text-sm text-slate-300">
              {formatPSF(result.prediction.predicted_price_per_sqft)}
            </p>
          </Card>
          {result.prediction.listed_price ? (
            <Card className="p-5">
              <p className="eyebrow text-ink-400">Listed vs estimated price</p>
              <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-xl font-bold text-ink-900">
                    {formatINR(result.prediction.listed_price)}
                  </p>
                  <p className="text-xs text-ink-400">Listed price</p>
                </div>
                <Badge tone={verdictTone(result.prediction.verdict)}>
                  <span className="inline-flex items-center gap-1">
                    <VerdictIcon size={12} />
                    {result.prediction.delta_pct > 0 ? "+" : ""}
                    {result.prediction.delta_pct}% · {result.prediction.verdict}
                  </span>
                </Badge>
              </div>
            </Card>
          ) : null}
          <div className="grid grid-cols-2 gap-3">
            <button onClick={() => onExplain(result)} className="action-tile">
              <Brain size={18} className="text-accent-teal" />
              <span>Why this price?</span>
              <small>View model drivers</small>
            </button>
            <button onClick={() => onWhatIf(result)} className="action-tile">
              <SlidersHorizontal size={18} className="text-accent-amber" />
              <span>Run what-if</span>
              <small>Test another scenario</small>
            </button>
          </div>
        </>
      )}
    </div>
  </div></div>;
}

function Field({ label, children }) { return <label className="block"><span className="mb-1.5 block text-xs font-medium text-ink-600">{label}</span>{children}</label>; }
