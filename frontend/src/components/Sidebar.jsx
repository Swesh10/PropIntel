import React from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  Calculator,
  Brain,
  SlidersHorizontal,
  Compass,
  Building2,
  Home,
  LogOut,
  CircleHelp,
  Settings,
  X,
} from "lucide-react";

const ICONS = {
  dashboard: LayoutDashboard,
  listings: Home,
  predict: Calculator,
  explain: Brain,
  whatif: SlidersHorizontal,
  recommend: Compass,
};

export default function Sidebar({ views, onSelect, user, onLogout, mobileOpen, onClose }) {
  const identity = user?.name || user?.email;
  const initials = identity ? identity.slice(0, 2).toUpperCase() : "PI";

  return (
    <>
      {mobileOpen && <button aria-label="Close navigation overlay" onClick={onClose} className="fixed inset-0 z-30 bg-navy-950/25 lg:hidden" />}
    <aside className={`fixed left-0 top-0 z-40 flex h-dvh w-[260px] flex-col overflow-y-auto border-r border-slate-200 bg-white text-ink-600 transition-transform lg:translate-x-0 ${mobileOpen ? "translate-x-0" : "-translate-x-full"}`}>
      <div className="flex h-[72px] items-center gap-3 border-b border-slate-100 px-5">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50 text-accent-teal">
          <Building2 size={20} />
        </div>
        <div>
          <p className="font-display text-lg font-bold leading-none text-ink-900">
            PropIntel
          </p>
          <p className="mt-1 text-[11px] text-ink-400">Maharashtra Property AI</p>
        </div>
        <button onClick={onClose} aria-label="Close navigation" className="ml-auto p-2 text-slate-400 hover:text-ink-900 lg:hidden"><X size={18} /></button>
      </div>

      <p className="px-5 pb-2 pt-7 text-[10px] font-bold uppercase tracking-[0.14em] text-slate-400">Workspace</p>
      <nav className="flex-1 space-y-1 px-3">
        {views.map((v) => {
          const Icon = ICONS[v.id];
          return (
            <NavLink
              key={v.id}
              to={`/${v.path}`}
              onClick={onSelect}
              className={({ isActive }) => `flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium leading-5 transition-colors ${
                isActive
                  ? "bg-emerald-50 text-accent-teal"
                  : "text-ink-600 hover:bg-slate-50 hover:text-ink-900"
              }`}
            >
              {({ isActive }) => (
                <>
                  <Icon size={18} strokeWidth={1.9} className={`shrink-0 ${isActive ? "text-accent-teal" : "text-slate-400"}`} />
                  <span className="min-w-0">{v.label}</span>
                </>
              )}
            </NavLink>
          );
        })}
      </nav>

      <div className="space-y-1 border-t border-slate-100 px-3 py-3">
        <div className="flex items-center gap-3 rounded-lg px-3 py-2 text-xs text-slate-400"><Settings size={16} /> Settings</div>
        <div className="flex items-center gap-3 rounded-lg px-3 py-2 text-xs text-slate-400"><CircleHelp size={16} /> Help &amp; Support</div>
      </div>
      <div className="border-t border-slate-100 px-4 py-3">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-bold text-ink-600">{initials}</span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-semibold text-ink-900">{identity || "Guest"}</p>
            <p className="mt-0.5 text-[10px] text-ink-400">{user ? "Signed-in account" : "Not signed in"}</p>
          </div>
          {user && <button onClick={onLogout} aria-label="Sign out" title="Sign out" className="rounded-lg p-2 text-slate-400 hover:bg-slate-50 hover:text-ink-900"><LogOut size={16} /></button>}
        </div>
      </div>
    </aside>
    </>
  );
}
