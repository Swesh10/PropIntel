import React from "react";

export function Card({ children, className = "" }) {
  return (
    <div className={`bg-card rounded-xl shadow-card border border-slate-200/80 ${className}`}>
      {children}
    </div>
  );
}

export function StatCard({ icon: Icon, label, value, sub, accent = "teal" }) {
  const accentMap = {
    teal: "bg-emerald-50 text-accent-teal",
    amber: "bg-amber-50 text-accent-amber",
    coral: "bg-rose-50 text-accent-coral",
  };
  return (
    <Card className="flex min-w-0 items-start justify-between gap-3 p-5">
      <div className="min-w-0">
        <p className="text-xs font-medium text-ink-400 uppercase tracking-wide">{label}</p>
        <p className="mt-1.5 break-words font-display text-2xl font-bold leading-tight text-ink-900">{value}</p>
        {sub && <p className="mt-1 text-xs leading-5 text-ink-400">{sub}</p>}
      </div>
      {Icon && (
        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${accentMap[accent]}`}>
          <Icon size={19} />
        </div>
      )}
    </Card>
  );
}

export function Badge({ children, tone = "neutral", title }) {
  const tones = {
    neutral: "bg-slate-100 text-slate-600",
    positive: "bg-emerald-50 text-emerald-700",
    negative: "bg-rose-50 text-rose-700",
    warning: "bg-amber-50 text-amber-700",
  };
  return (
    <span title={title} className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold ${tones[tone]}`}>
      {children}
    </span>
  );
}

export function formatINR(value) {
  if (value === null || value === undefined || isNaN(value)) return "—";
  const num = Number(value);
  if (num >= 10000000) return `₹ ${(num / 10000000).toFixed(2)} Cr`;
  if (num >= 100000) return `₹ ${(num / 100000).toFixed(1)} Lakh`;
  return `₹ ${num.toLocaleString("en-IN")}`;
}

export function formatPSF(value) {
  if (value === null || value === undefined || isNaN(value)) return "—";
  return `₹ ${Math.round(Number(value)).toLocaleString("en-IN")}/sq.ft`;
}

export function SectionHeader({ title, subtitle, right }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0 flex-1">
        <h1 className="break-words font-display text-2xl font-bold leading-tight text-ink-900">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-xl text-sm leading-5 text-ink-600">{subtitle}</p>}
      </div>
      {right && <div className="max-w-full shrink-0">{right}</div>}
    </div>
  );
}

export function Spinner({ label = "Loading…" }) {
  return (
    <div className="flex items-center gap-2.5 text-ink-400 text-sm py-8 justify-center">
      <span className="w-4 h-4 rounded-full border-2 border-slate-200 border-t-accent-teal animate-spin" />
      {label}
    </div>
  );
}
