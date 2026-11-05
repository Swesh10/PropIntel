import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Building2, Heart, Search, SlidersHorizontal } from "lucide-react";
import { api } from "../api.js";
import { Badge, Card, SectionHeader, Spinner, formatINR, formatPSF } from "./Shared.jsx";

const PROPERTY_IMAGES = [
  "https://images.unsplash.com/photo-1600607687920-4e2a09cf159d?auto=format&fit=crop&w=640&q=75",
  "https://images.unsplash.com/photo-1600566753190-17f0baa2a6c3?auto=format&fit=crop&w=640&q=75",
  "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=640&q=75",
  "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?auto=format&fit=crop&w=640&q=75",
  "https://images.unsplash.com/photo-1570129477492-45c003edd2be?auto=format&fit=crop&w=640&q=75",
  "https://images.unsplash.com/photo-1576941089067-2de3c901e126?auto=format&fit=crop&w=640&q=75",
  "https://images.unsplash.com/photo-1580587771525-78b9dba3b914?auto=format&fit=crop&w=640&q=75",
  "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?auto=format&fit=crop&w=640&q=75",
  "https://images.unsplash.com/photo-1523217582562-09d0def993a6?auto=format&fit=crop&w=640&q=75",
  "https://images.unsplash.com/photo-1449844908441-8829872d2607?auto=format&fit=crop&w=640&q=75",
];

export default function PropertyListings({ meta, user }) {
  const [searchParams] = useSearchParams();
  const [listings, setListings] = useState([]);
  const [filters, setFilters] = useState({ locality: "", property_type: "", bhk: "", budget_max: null, area_min: 0 });
  const [matchingCount, setMatchingCount] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState(() => searchParams.get("search") || "");
  const [saved, setSaved] = useState([]);
  const pageSize = 24;
  const catalogMaxBudget = Number(meta?.stats?.max_listed_price) || 0;
  const budgetMax = filters.budget_max ?? catalogMaxBudget;

  useEffect(() => {
    setSearch(searchParams.get("search") || "");
    setOffset(0);
  }, [searchParams]);

  useEffect(() => {
    if (!user) {
      setListings([]);
      setMatchingCount(0);
      setLoading(false);
      setError("Sign in to browse the live Mumbai listing catalog.");
      return undefined;
    }
    if (!meta) return undefined;
    let active = true;
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError("");
      api.listings({
        locality: filters.locality,
        property_type: filters.property_type,
        bhk: filters.bhk,
        budget_max: filters.budget_max ?? undefined,
        area_min: filters.area_min,
        search: search.trim(),
        limit: pageSize,
        offset,
      })
        .then((response) => {
          if (!active) return;
          setListings(response.results || []);
          setMatchingCount(response.count || 0);
        })
        .catch((err) => {
          if (active) setError(err.message);
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    }, 200);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [filters, meta, offset, pageSize, search, user]);

  const toggleSaved = (id) => setSaved((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  const updateFilter = (field, value) => {
    setOffset(0);
    setFilters((current) => ({ ...current, [field]: value }));
  };
  const clearFilters = () => {
    setSearch("");
    setFilters({ locality: "", property_type: "", bhk: "", budget_max: null, area_min: 0 });
    setOffset(0);
  };
  const activeFilters = [
    search.trim() && `Search: “${search.trim()}”`,
    filters.locality && `Locality: ${filters.locality}`,
    filters.property_type && `Property type: ${filters.property_type}`,
    filters.bhk && `${filters.bhk} BHK`,
    filters.budget_max !== null && filters.budget_max < catalogMaxBudget && `Budget up to ${formatINR(filters.budget_max)}`,
    filters.area_min > 0 && `Minimum area: ${filters.area_min.toLocaleString("en-IN")} sq.ft.`,
  ].filter(Boolean);
  const pageCount = Math.ceil(matchingCount / pageSize);
  const firstResult = matchingCount ? offset + 1 : 0;
  const lastResult = Math.min(offset + pageSize, matchingCount);

  return (
    <div>
      <SectionHeader title="Mumbai listings" subtitle="Browse residential sale listings from the cleaned catalog. Asking prices and details come directly from the dataset." right={<span className="data-chip"><Building2 size={14} /> {matchingCount.toLocaleString("en-IN")} matches</span>} />
      <Card className="mb-5 p-4 sm:p-5">
        <div className="flex flex-col gap-4">
          <label className="relative block">
            <Search size={17} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
            <input list="propintel-locality-suggestions" className="input input-with-icon" value={search} onChange={(event) => { setSearch(event.target.value); setOffset(0); }} placeholder="Search locality, zone, or property type" />
            <datalist id="propintel-locality-suggestions">
              {(meta?.localities || []).map((locality) => <option key={locality} value={locality} />)}
            </datalist>
          </label>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <select className="input" value={filters.locality} onChange={(event) => updateFilter("locality", event.target.value)}><option value="">All localities</option>{(meta?.localities || []).map((locality) => <option key={locality}>{locality}</option>)}</select>
            <select className="input" value={filters.property_type} onChange={(event) => updateFilter("property_type", event.target.value)}><option value="">All property types</option>{(meta?.property_types || []).map((type) => <option key={type}>{type}</option>)}</select>
            <select className="input" value={filters.bhk} onChange={(event) => updateFilter("bhk", event.target.value)}><option value="">Any BHK</option>{[1, 2, 3, 4, 5].map((number) => <option key={number} value={number}>{number} BHK</option>)}</select>
            <label className="text-xs font-medium text-ink-600">Budget up to {formatINR(budgetMax)}<input type="range" min="1000000" max={catalogMaxBudget || 1} step="500000" value={budgetMax} onChange={(event) => updateFilter("budget_max", Number(event.target.value))} className="mt-2 w-full slider-thumb" disabled={!catalogMaxBudget} /></label>
            <label className="text-xs font-medium text-ink-600">Minimum area {filters.area_min.toLocaleString("en-IN")} sq.ft<input type="range" min="0" max="5000" step="100" value={filters.area_min} onChange={(event) => updateFilter("area_min", Number(event.target.value))} className="mt-2 w-full slider-thumb" /></label>
          </div>
          {activeFilters.length > 0 && <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3"><p className="text-xs text-ink-500">Active filters: {activeFilters.join(" · ")}</p><button type="button" className="text-xs font-semibold text-accent-teal hover:underline" onClick={clearFilters}>Clear filters</button></div>}
        </div>
      </Card>
    {error && <div role="alert" className="error-banner mb-5">{error}{error.toLowerCase().includes("authentication") && " Sign in from the top-right to browse the catalog."}</div>}
      {loading ? <Card><Spinner label="Loading genuine Mumbai listings..." /></Card> : <>
        <p className="mb-3 text-xs text-ink-500">Showing {firstResult.toLocaleString("en-IN")}–{lastResult.toLocaleString("en-IN")} of {matchingCount.toLocaleString("en-IN")} matching listings</p>
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">{listings.map((listing, index) => <ListingCard key={listing.id} listing={listing} image={PROPERTY_IMAGES[(offset + index) % PROPERTY_IMAGES.length]} priority={index === 0} saved={saved.includes(listing.id)} onSave={() => toggleSaved(listing.id)} />)}{!listings.length && <Card className="col-span-full p-10 text-center"><SlidersHorizontal className="mx-auto mb-3 text-slate-300" /><p className="font-semibold text-ink-800">No listings match this filter combination.</p>{activeFilters.length > 0 ? <><p className="mt-2 text-sm text-ink-500">The selected filters have no matching records: {activeFilters.join(" · ")}</p><button type="button" className="mt-4 text-sm font-semibold text-accent-teal hover:underline" onClick={clearFilters}>Clear filters and show all listings</button></> : <p className="mt-2 text-sm text-ink-500">There are no listings available in the catalog right now.</p>}</Card>}</div>
        {pageCount > 1 && <div className="mt-5 flex items-center justify-center gap-4"><button type="button" className="button-secondary" disabled={offset === 0} onClick={() => setOffset((current) => Math.max(0, current - pageSize))}>Previous</button><span className="text-sm text-ink-500">Page {Math.floor(offset / pageSize) + 1} of {pageCount}</span><button type="button" className="button-secondary" disabled={offset + pageSize >= matchingCount} onClick={() => setOffset((current) => current + pageSize)}>Next</button></div>}
      </>}
    </div>
  );
}

function ListingCard({ listing, image, priority, saved, onSave }) {
  return (
    <article className="listing-card">
      <div className="relative h-48 overflow-hidden bg-slate-100">
        <img
          src={image}
          alt="Mumbai residential property"
          loading={priority ? "eager" : "lazy"}
          decoding="async"
          className="h-full w-full object-cover transition duration-500 hover:scale-105"
          onError={(event) => {
            event.currentTarget.src = "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=640&q=75";
          }}
        />
        <div className="absolute inset-x-0 top-0 flex items-start justify-between p-3">
          <Badge tone="neutral">{listing.property_type}</Badge>
          <button
            aria-label={saved ? "Remove saved listing" : "Save listing"}
            onClick={onSave}
            className={`icon-button ${saved ? "text-rose-600" : "text-ink-600"}`}
          >
            <Heart size={17} fill={saved ? "currentColor" : "none"} />
          </button>
        </div>
      </div>
      <div className="min-w-0 p-5">
        <p className="break-words text-xs font-semibold uppercase tracking-[0.12em] text-accent-teal">{listing.locality}</p>
        <h3 className="mt-1 break-words font-display text-xl font-bold text-ink-900">{listing.bhk} BHK residence</h3>
        <p className="mt-1 break-words text-sm leading-5 text-ink-600">
          {listing.city} · {Number(listing.area_sqft).toLocaleString("en-IN")} sq.ft · {listing.furnishing}
        </p>
        <div className="mt-5 flex flex-wrap items-end gap-3">
          <div className="min-w-0">
            <p className="break-words font-display text-xl font-bold text-ink-900">{formatINR(listing.listed_price)}</p>
            <p className="mt-1 text-xs text-ink-400">{formatPSF(listing.listed_price / listing.area_sqft)}</p>
          </div>
        </div>
      </div>
    </article>
  );
}
