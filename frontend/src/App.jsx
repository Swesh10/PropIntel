import React, { lazy, Suspense, useEffect, useState } from "react";
import { Bell, ChevronDown, CircleHelp, LogIn, LogOut, Menu, Search, Settings } from "lucide-react";
import { Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import Sidebar from "./components/Sidebar.jsx";
import { api } from "./api.js";

const Dashboard = lazy(() => import("./components/Dashboard.jsx"));
const PropertyListings = lazy(() => import("./components/PropertyListings.jsx"));
const PricePrediction = lazy(() => import("./components/PricePrediction.jsx"));
const ExplainableAI = lazy(() => import("./components/ExplainableAI.jsx"));
const WhatIfAnalysis = lazy(() => import("./components/WhatIfAnalysis.jsx"));
const Recommendations = lazy(() => import("./components/Recommendations.jsx"));
const Login = lazy(() => import("./components/Login.jsx"));

const VIEWS = [
  { id: "dashboard", path: "dashboard", label: "Dashboard" },
  { id: "listings", path: "listings", label: "Mumbai Listings" },
  { id: "predict", path: "predict", label: "Price Prediction" },
  { id: "explain", path: "explain", label: "Explainable AI" },
  { id: "whatif", path: "what-if", label: "What-If Analysis" },
  { id: "recommend", path: "recommendations", label: "Recommendations" },
];

export default function App() {
  const navigate = useNavigate();
  const location = useLocation();
  const activeView = VIEWS.find((view) => view.path === location.pathname.split("/").filter(Boolean)[0])?.id || "dashboard";
  const [user, setUser] = useState(null);
  const [meta, setMeta] = useState(null);
  const [metaError, setMetaError] = useState("");
  const [authError, setAuthError] = useState("");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false);
  const [lastPrediction, setLastPrediction] = useState(null); // shared between Predict -> Explain/What-If

  useEffect(() => {
    api.getMeta().then(setMeta).catch((error) => setMetaError(error.message));
  }, []);

  useEffect(() => {
    localStorage.removeItem("propintel_token");
    sessionStorage.removeItem("propintel_token");
    localStorage.removeItem("propintel_user");
    sessionStorage.removeItem("propintel_user");
    api.restoreSession()
      .then((result) => {
        if (result?.user) setUser(result.user);
      })
      .catch((error) => setAuthError(error.message));
  }, []);

  useEffect(() => {
    if (location.pathname === "/reset-password") setLoginOpen(true);
  }, [location.pathname]);

  const navigateTo = (viewId) => {
    const view = VIEWS.find((item) => item.id === viewId);
    if (view) navigate(`/${view.path}`);
    setMobileNavOpen(false);
  };

  const goToExplain = (predictionResult) => {
    setLastPrediction(predictionResult);
    navigateTo("explain");
  };

  const goToWhatIf = (predictionResult) => {
    setLastPrediction(predictionResult);
    navigateTo("whatif");
  };

  const storeAuthenticatedUser = (result) => {
    if (!result?.access_token || !result?.user) return;
    api.setAccessToken(result.access_token);
    setUser(result.user);
    setAuthError("");
  };

  const handleLogin = async ({ email, password, remember }) => {
    const result = await api.login(email, password, remember);
    storeAuthenticatedUser(result);
    return result;
  };

  const handleRegister = async ({ name, email, password, remember }) => {
    return api.register(name, email, password, remember);
  };

  const handleAuthenticated = (result) => storeAuthenticatedUser(result);

  const handleLogout = async () => {
    const logoutRequest = api.logout();
    setUser(null);
    try {
      await logoutRequest;
      setAuthError("");
    } catch (error) {
      setAuthError(`You have been signed out locally, but server session revocation failed: ${error.message}`);
    }
  };

  return (
    <div className="min-h-screen bg-surface">
      <Sidebar views={VIEWS} activeView={activeView} onSelect={() => setMobileNavOpen(false)} user={user} onLogout={handleLogout} mobileOpen={mobileNavOpen} onClose={() => setMobileNavOpen(false)} />
      <main className="min-h-screen lg:ml-64">
        <TopHeader
          user={user}
          onOpenMenu={() => setMobileNavOpen(true)}
          onSignIn={() => setLoginOpen(true)}
          onSignOut={handleLogout}
          onSearch={(query) => navigate(`/listings?search=${encodeURIComponent(query)}`)}
        />
        <div className="mx-auto max-w-[1440px] px-4 py-6 sm:px-7 lg:px-9 lg:py-8">
          {metaError && <div role="alert" className="mb-5 flex items-center justify-between gap-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"><span>{metaError} Some dashboard metrics may be unavailable.</span><button onClick={() => window.location.reload()} className="font-bold underline">Retry</button></div>}
          {authError && <div role="alert" className="mb-5 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{authError}</div>}
          <Suspense fallback={<div className="grid min-h-[40vh] place-items-center text-sm text-ink-400" role="status">Loading workspace…</div>}>
            <Routes>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/:pageId" element={<DynamicPage meta={meta} user={user} onNavigate={navigateTo} onExplain={goToExplain} onWhatIf={goToWhatIf} lastPrediction={lastPrediction} />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
          </Suspense>
        </div>
      </main>
      {loginOpen && (
        <Suspense fallback={<div className="fixed inset-0 z-50 grid place-items-center bg-navy-950/25" role="status">Loading sign in…</div>}>
          <Login
            onLogin={handleLogin}
            onRegister={handleRegister}
            onAuthenticated={handleAuthenticated}
            resetToken={new URLSearchParams(location.search).get("token") || ""}
            onClose={() => {
              setLoginOpen(false);
              if (location.pathname === "/reset-password") navigate("/dashboard", { replace: true });
            }}
          />
        </Suspense>
      )}
    </div>
  );
}

function TopHeader({ user, onOpenMenu, onSignIn, onSignOut, onSearch }) {
  const [query, setQuery] = useState("");
  const [profileOpen, setProfileOpen] = useState(false);
  const identity = user?.name || user?.email;
  const initials = identity ? identity.slice(0, 2).toUpperCase() : "PI";

  const submitSearch = (event) => {
    event.preventDefault();
    if (query.trim()) onSearch(query.trim());
  };

  return (
    <header className="sticky top-0 z-20 flex h-[72px] items-center gap-3 border-b border-slate-200/80 bg-white/95 px-4 backdrop-blur sm:px-7 lg:px-9">
      <button onClick={onOpenMenu} aria-label="Open navigation" className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-slate-200 text-ink-600 lg:hidden">
        <Menu size={19} />
      </button>
      <form onSubmit={submitSearch} className="relative min-w-0 w-full max-w-xl flex-1">
        <Search size={17} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
        <input
          aria-label="Search localities, areas, or properties"
          className="input input-with-icon border-transparent bg-slate-50 pr-4 focus:border-emerald-300"
          placeholder="Search..."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </form>
      <div className="ml-auto flex shrink-0 items-center gap-2 sm:gap-4">
        <span aria-label="No new notifications" title="No new notifications" className="relative inline-flex h-10 w-10 items-center justify-center rounded-lg text-slate-500">
          <Bell size={18} />
          <span className="absolute right-2 top-2 h-1.5 w-1.5 rounded-full bg-accent-teal" />
        </span>
        <div className="relative">
          <button
            onClick={() => user ? setProfileOpen((open) => !open) : onSignIn()}
            aria-expanded={profileOpen}
            className="flex items-center gap-2 rounded-lg p-1.5 text-left hover:bg-slate-50"
          >
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-50 text-xs font-bold text-accent-teal">{initials}</span>
            <span className="hidden max-w-48 sm:block">
              <span className="block truncate text-xs font-semibold text-ink-900">{identity || "Sign in"}</span>
              <span className="mt-0.5 block text-[11px] text-ink-400">{user ? "Signed-in account" : "Access your workspace"}</span>
            </span>
            <ChevronDown size={15} className="hidden text-slate-400 sm:block" />
          </button>
          {profileOpen && user && (
            <div className="absolute right-0 top-12 w-44 rounded-lg border border-slate-200 bg-white p-1.5 shadow-lg">
              <button onClick={() => { onSignOut(); setProfileOpen(false); }} className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-ink-600 hover:bg-slate-50">
                <LogOut size={15} /> Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

function DynamicPage({ meta, user, onNavigate, onExplain, onWhatIf, lastPrediction }) {
  const { pageId } = useParams();
  const view = VIEWS.find((item) => item.path === pageId);

  switch (view?.id) {
    case "dashboard":
      return <Dashboard meta={meta} onNavigate={onNavigate} />;
    case "listings":
      return <PropertyListings meta={meta} user={user} />;
    case "predict":
      return <PricePrediction meta={meta} onExplain={onExplain} onWhatIf={onWhatIf} />;
    case "explain":
      return <ExplainableAI meta={meta} initialPrediction={lastPrediction} onNavigateToPredict={() => onNavigate("predict")} />;
    case "whatif":
      return <WhatIfAnalysis meta={meta} initialPrediction={lastPrediction} onNavigateToPredict={() => onNavigate("predict")} />;
    case "recommend":
      return <Recommendations meta={meta} user={user} />;
    default:
      return <div role="alert" className="rounded-lg border border-[#e5dfd2] bg-card p-6"><h1 className="font-display text-2xl font-bold text-ink-900">Page not found</h1><button onClick={() => onNavigate("dashboard")} className="button-primary mt-4">Return to dashboard</button></div>;
  }
}
