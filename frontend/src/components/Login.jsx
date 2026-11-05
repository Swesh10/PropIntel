import React, { useState } from "react";
import { ArrowRight, Building2, Eye, EyeOff, LockKeyhole, Mail, UserRound } from "lucide-react";
import { api } from "../api.js";

export default function Login({ onLogin, onRegister, onAuthenticated, onClose, resetToken = "" }) {
  const [mode, setMode] = useState(resetToken ? "reset" : "login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    if (mode === "forgot") {
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
        setError("Enter a valid email address.");
        return;
      }
    } else if (mode === "reset") {
      if (!resetToken) {
        setError("This password reset link is invalid or missing its token.");
        return;
      }
      if (password.length < 12 || !/[A-Za-z]/.test(password) || !/[\d\W]/.test(password)) {
        setError("Use at least 12 characters with letters and a number or symbol.");
        return;
      }
      if (password !== confirmPassword) {
        setError("The passwords do not match.");
        return;
      }
    }
    if (mode === "register" && !name.trim()) {
      setError("Enter your name to create an account.");
      return;
    }
    if (!["reset", "forgot"].includes(mode) && (!email.trim() || !password)) {
      setError("Enter your email and password to continue.");
      return;
    }
    if (!["reset", "forgot"].includes(mode) && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setError("Enter a valid email address.");
      return;
    }
    if (mode === "register" && (password.length < 12 || !/[A-Za-z]/.test(password) || !/[\d\W]/.test(password))) {
      setError("Use at least 12 characters with letters and a number or symbol.");
      return;
    }
    if (mode === "register" && password !== confirmPassword) {
      setError("The passwords do not match.");
      return;
    }
    setSubmitting(true);
    setError("");
    setMessage("");
    try {
      if (mode === "forgot") {
        const result = await api.forgotPassword(email.trim());
        setMessage(result.message);
      } else if (mode === "reset") {
        const result = await api.resetPassword(resetToken, password);
        setMode("login");
        setPassword("");
        setConfirmPassword("");
        setMessage(result.message);
      } else {
        const credentials = { email: email.trim(), password, remember };
        const result = mode === "register"
          ? await onRegister({ ...credentials, name: name.trim() })
          : await onLogin(credentials);
        if (mode === "register" && result?.access_token) onAuthenticated(result);
        if (result?.access_token) onClose?.();
      }
    } catch (authError) {
      setError(authError.message);
    } finally {
      setSubmitting(false);
    }
  };

  const switchMode = (nextMode) => {
    setMode(nextMode);
    setError("");
    setMessage("");
  };
  const registering = mode === "register";
  const needsEmail = mode === "login" || mode === "register" || mode === "forgot";
  const needsPassword = mode === "login" || mode === "register" || mode === "reset";
  const heading = {
    login: "Sign in to your workspace",
    register: "Create your account",
    forgot: "Reset your password",
    reset: "Choose a new password",
  }[mode];
  const description = {
    login: "Your property intelligence, ready when you are.",
    register: "Create an account to explore Maharashtra property insights.",
    forgot: "If an account exists, we will send password reset instructions.",
    reset: "Choose a strong password to secure your account.",
  }[mode];

  return (
    <main className={`${onClose ? "fixed inset-0 z-50 bg-navy-950/25 overflow-y-auto" : "min-h-screen bg-surface"} flex items-center justify-center px-5 py-10`}>
      <div className="w-full max-w-5xl grid lg:grid-cols-[1.05fr_0.95fr] bg-card rounded-2xl border border-slate-200 shadow-card overflow-hidden">
        <section className="hidden lg:flex relative overflow-hidden bg-emerald-50 p-12 text-ink-900 flex-col justify-between min-h-[620px]">
          <div className="absolute -right-24 -top-24 w-72 h-72 rounded-full border border-accent-teal/15" />
          <div className="absolute -right-8 top-8 w-40 h-40 rounded-full border border-accent-amber/20" />
          <div className="relative flex items-center gap-3">
            <div className="w-11 h-11 rounded-xl bg-accent-amber flex items-center justify-center">
              <Building2 size={23} />
            </div>
            <div>
              <p className="font-display text-xl font-bold">PropIntel</p>
              <p className="text-xs text-ink-600">Maharashtra Property AI</p>
            </div>
          </div>
          <div className="relative max-w-md">
            <p className="text-accent-teal text-xs font-bold uppercase tracking-[0.2em]">Intelligence for every address</p>
            <h1 className="font-display text-4xl font-bold leading-tight mt-4">Read the market before you make your move.</h1>
            <p className="text-ink-600 mt-5 leading-relaxed">Use property price estimates, local market signals, and explainable insights to make clearer property decisions.</p>
          </div>
          <p className="relative text-xs text-ink-400">Private workspace for Maharashtra property intelligence.</p>
        </section>

        <section className="relative p-7 sm:p-12 flex flex-col justify-center">
          {onClose && <button type="button" onClick={onClose} aria-label="Close authentication" className="absolute right-5 top-5 text-ink-400 hover:text-ink-900 text-2xl leading-none">&times;</button>}
          <div className="lg:hidden flex items-center gap-3 mb-12">
            <div className="w-10 h-10 rounded-xl bg-accent-amber text-white flex items-center justify-center"><Building2 size={21} /></div>
            <div><p className="font-display text-lg font-bold text-ink-900">PropIntel</p><p className="text-xs text-ink-400">Maharashtra Property AI</p></div>
          </div>
          <div className="max-w-sm w-full mx-auto">
            <p className="text-xs font-bold uppercase tracking-[0.18em] text-accent-teal">
              {registering ? "Get started" : mode === "login" ? "Welcome back" : "Account security"}
            </p>
            <h2 className="font-display text-3xl font-bold text-ink-900 mt-3">
              {heading}
            </h2>
            <p className="text-sm text-ink-600 mt-2">
              {description}
            </p>

            <form onSubmit={submit} className="mt-8 space-y-5">
              {registering && (
                <label className="block">
                  <span className="block text-xs font-semibold text-ink-600 mb-2">Full name</span>
                  <span className="relative block">
                    <UserRound size={17} className="absolute left-3.5 top-3.5 text-ink-400" />
                    <input value={name} onChange={(event) => setName(event.target.value)} type="text" placeholder="Your name" className="input input-with-icon" autoComplete="name" maxLength={100} />
                  </span>
                </label>
              )}
              {needsEmail && <label className="block">
                <span className="block text-xs font-semibold text-ink-600 mb-2">Work email</span>
                <span className="relative block">
                  <Mail size={17} className="absolute left-3.5 top-3.5 text-ink-400" />
                  <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" placeholder="you@company.com" className="input input-with-icon" autoComplete="email" />
                </span>
              </label>}
              {needsPassword && <label className="block">
                <span className="block text-xs font-semibold text-ink-600 mb-2">{mode === "reset" ? "New password" : "Password"}</span>
                <span className="relative block">
                  <LockKeyhole size={17} className="absolute left-3.5 top-3.5 text-ink-400" />
                  <input value={password} onChange={(event) => setPassword(event.target.value)} type={showPassword ? "text" : "password"} placeholder={registering || mode === "reset" ? "At least 12 characters with letters and a number or symbol" : "Enter your password"} className="input input-with-icon input-with-action" autoComplete={registering || mode === "reset" ? "new-password" : "current-password"} maxLength={128} />
                  <button type="button" aria-label={showPassword ? "Hide password" : "Show password"} onClick={() => setShowPassword((visible) => !visible)} className="absolute right-3 top-2.5 p-1 text-ink-400 hover:text-ink-900">
                    {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </span>
              </label>}
              {(registering || mode === "reset") && (
                <label className="block">
                  <span className="block text-xs font-semibold text-ink-600 mb-2">Confirm password</span>
                  <span className="relative block">
                    <LockKeyhole size={17} className="absolute left-3.5 top-3.5 text-ink-400" />
                    <input value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} type={showPassword ? "text" : "password"} placeholder="Enter your password again" className="input input-with-icon" autoComplete="new-password" maxLength={128} />
                  </span>
                </label>
              )}
              {(mode === "login" || mode === "register") && <div className="flex items-center justify-between gap-3">
                <label className="inline-flex items-center gap-2 text-xs text-ink-600 cursor-pointer">
                  <input type="checkbox" checked={remember} onChange={(event) => setRemember(event.target.checked)} className="accent-accent-amber" />
                  Remember me
                </label>
                {mode === "login" && (
                  <button
                    type="button"
                    className="text-xs font-semibold text-accent-teal hover:underline"
                    onClick={() => switchMode("forgot")}
                  >
                    Forgot password?
                  </button>
                )}
              </div>}
              {message && <p role="status" className="text-xs font-medium text-accent-teal">{message}</p>}
              {error && <p role="alert" className="text-xs font-medium text-accent-coral">{error}</p>}
              <button type="submit" disabled={submitting} className="w-full bg-accent-teal text-white font-bold text-sm py-3 rounded-lg hover:bg-teal-700 transition-colors flex items-center justify-center gap-2 disabled:opacity-60">
                {submitting ? "Please wait..." : ({
                  login: "Enter PropIntel",
                  register: "Create account",
                  forgot: "Send reset instructions",
                  reset: "Reset password",
                })[mode]}
                {!submitting && <ArrowRight size={16} />}
              </button>
            </form>
            {mode === "login" || registering ? <p className="text-center text-xs text-ink-400 mt-8">
              {registering ? "Already have an account? " : "New to PropIntel? "}
              <button type="button" onClick={() => switchMode(registering ? "login" : "register")} className="font-semibold text-accent-teal hover:underline">
                {registering ? "Sign in" : "Create an account"}
              </button>
            </p> : <button type="button" onClick={() => switchMode("login")} className="mt-8 w-full text-center text-xs font-semibold text-accent-teal hover:underline">Back to sign in</button>}
          </div>
        </section>
      </div>
    </main>
  );
}
