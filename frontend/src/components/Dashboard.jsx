import React, { lazy, Suspense, useEffect, useState } from "react";
import { ArrowDownRight, ArrowUpRight, BarChart3, Building2, MapPin, Search, Sparkles } from "lucide-react";
import { Card, SectionHeader, Spinner, StatCard, formatPSF } from "./Shared.jsx";
import { api } from "../api.js";

const DashboardCharts = lazy(() => import("./DashboardCharts.jsx"));

export default function Dashboard({ meta, onNavigate }) {
  const [trends, setTrends] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    api.marketTrends().then(setTrends).catch((err) => setError(err.message)).finally(() => setLoading(false));
  }, []);

  const cityData = Object.entries(trends?.avg_price_per_sqft_by_city || {}).map(([city, psf]) => ({ city, psf }));
  const chartCityData = cityData.slice(0, 8);
  const bhkData = Object.entries(trends?.bhk_distribution || {}).map(([bhk, count]) => ({ bhk: `${bhk} BHK`, count }));
  const leadCity = cityData[0];
  const affordableCity = cityData[cityData.length - 1];
  const localities = (meta?.localities || []).slice(0, 5);

  return (
    <div className="space-y-6">
      <section className="hero-panel">
        <div className="relative z-10 max-w-[58%]">
          <p className="eyebrow text-accent-teal"><Sparkles size={14} /> Mumbai market intelligence</p>
          <h1 className="mt-4 max-w-xl font-display text-3xl font-bold leading-tight text-ink-900 sm:text-4xl">Explore Mumbai&apos;s<br className="hidden sm:block" /> property market with AI.</h1>
          <p className="mt-3 max-w-lg text-sm leading-6 text-ink-600">Explore cleaned sale listings, compare localities, and use the trained PropIntel model to analyze property prices before you commit.</p>
          <div className="mt-6 flex flex-wrap gap-3"><button onClick={() => onNavigate("predict")} className="button-primary">Price a property <ArrowUpRight size={16} /></button><button onClick={() => onNavigate("listings")} className="button-secondary">Browse listings <Search size={16} /></button></div>
        </div>
        <div className="hero-visual"><img src="https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=900&q=70" alt="Modern residential property" decoding="async" onError={(e) => { e.currentTarget.style.display = 'none'; }} /></div>
        <div className="hero-stamp"><span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-white/75">Dataset coverage</span><strong>{meta?.stats?.total_properties?.toLocaleString("en-IN") || "—"}</strong><span className="text-xs text-white/85">clean sale listings</span></div>
      </section>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <StatCard icon={Building2} label="Clean sale listings" value={meta ? meta.stats.total_properties.toLocaleString("en-IN") : "—"} sub="After normalization and outlier filtering" accent="teal" />
        <StatCard icon={MapPin} label="Market zones" value={meta ? meta.stats.cities_covered : "—"} sub={meta ? `${(meta.cities || []).join(", ")}` : "Loading catalog…"} accent="amber" />
        <StatCard icon={BarChart3} label="Blended price / sq.ft" value={meta ? formatPSF(meta.stats.avg_price_per_sqft) : "—"} sub="Calculated from the cleaned catalog" accent="coral" />
      </div>

      {error && <div role="alert" className="error-banner">{error}</div>}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.25fr_0.9fr]">
        <Card className="min-w-0 p-5 sm:p-6">
          <SectionHeader title="Where the market is priced" subtitle="Average listing price per sq.ft across the actual Mumbai dataset." right={<span className="data-chip">₹ / sq.ft.</span>} />
          {loading ? <Spinner label="Loading market data..." /> : <Suspense fallback={<Spinner label="Preparing market chart..." />}><DashboardCharts data={chartCityData} type="city" /></Suspense>}
        </Card>
        <Card className="min-w-0 p-5 sm:p-6">
          <SectionHeader title="Demand by configuration" subtitle="Clean listings grouped by bedroom count." right={<span className="data-chip">By bedrooms</span>} />
          {loading ? <Spinner label="Loading market data..." /> : <Suspense fallback={<Spinner label="Preparing market chart..." />}><DashboardCharts data={bhkData} type="bedrooms" /></Suspense>}
        </Card>
      </div>
      <section>
        <SectionHeader title="Market insights" subtitle="Signals calculated from the current city-level price averages." />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <InsightCard icon={ArrowUpRight} label="Highest average zone" city={leadCity?.city} value={leadCity ? formatPSF(leadCity.psf) : "—"} tone="teal" />
          <InsightCard icon={ArrowDownRight} label="Lowest average zone" city={affordableCity?.city} value={affordableCity ? formatPSF(affordableCity.psf) : "—"} tone="amber" />
          <InsightCard icon={BarChart3} label="Catalog sample size" city={trends ? trends.total_properties.toLocaleString("en-IN") : "Waiting for market data"} value="Clean sale listings in this snapshot" tone="blue" />
        </div>
      </section>
      <Card className="p-5 sm:p-6">
        <SectionHeader title="Localities in the catalog" subtitle="Locality names provided by the live property catalog." right={<button onClick={() => onNavigate("listings")} className="button-outline">View all <ArrowUpRight size={15} /></button>} />
        {localities.length ? (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {localities.map((locality) => <div key={locality} className="flex items-center gap-3 rounded-lg border border-slate-100 px-3.5 py-3"><MapPin size={16} className="shrink-0 text-accent-teal" /><span className="truncate text-sm font-medium text-ink-900">{locality}</span></div>)}
          </div>
        ) : <p className="text-sm text-ink-400">Localities will appear when catalog metadata loads.</p>}
        <p className="mt-3 text-xs text-ink-400">{meta?.localities?.length || 0} localities covered</p>
      </Card>
    </div>
  );
}

function InsightCard({ icon: Icon, label, city, value, tone }) {
  const tones = {
    teal: "bg-emerald-50 text-accent-teal",
    amber: "bg-amber-50 text-amber-600",
    blue: "bg-blue-50 text-blue-600",
  };
  return <Card className="flex min-w-0 items-start gap-3.5 p-4">
    <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${tones[tone]}`}><Icon size={18} /></span>
    <div className="min-w-0">
      <p className="text-xs font-medium text-ink-400">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold text-ink-900">{city || "—"}</p>
      <p className="mt-1 text-xs text-ink-600">{value}</p>
    </div>
  </Card>;
}
