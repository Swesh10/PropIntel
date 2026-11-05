const BASE = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/+$/, "");
let accessToken = null;
let csrfToken = null;
let refreshInFlight = null;

async function handle(res) {
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") {
        message = body.detail;
      } else if (Array.isArray(body.detail)) {
        const validationMessages = body.detail
          .map((item) => {
            const field = Array.isArray(item.loc) ? item.loc.slice(1).join(" ") : "";
            return field ? `${field}: ${item.msg}` : item.msg;
          })
          .filter(Boolean);
        message = validationMessages.join("; ") || body.message || message;
      } else {
        message = body.message || message;
      }
    } catch {
      // Keep a safe, useful message when the server does not return JSON.
    }
    throw new Error(message);
  }
  return res.json();
}

async function request(url, options = {}, allowRefresh = true) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 12000);
  const headers = { ...(options.headers || {}) };
  if (accessToken && !headers.Authorization) {
    headers.Authorization = `Bearer ${accessToken}`;
  }
  try {
    const response = await fetch(url, {
      ...options,
      headers,
      credentials: "include",
      signal: controller.signal,
    });
    if (
      response.status === 401 &&
      allowRefresh &&
      accessToken &&
      !url.includes("/auth/")
    ) {
      await refreshSession();
      return request(url, options, false);
    }
    return await handle(response);
  } catch (error) {
    if (error.name === "AbortError") throw new Error("The request timed out. Please try again.");
    if (error instanceof TypeError) throw new Error("Unable to reach the PropIntel API.");
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function refreshSession() {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      const csrf = await request(`${BASE}/auth/csrf`, {}, false);
      csrfToken = csrf.csrf_token;
      const result = await request(
        `${BASE}/auth/refresh`,
        {
          method: "POST",
          headers: { "X-CSRF-Token": csrfToken },
        },
        false
      );
      accessToken = result.access_token;
      csrfToken = result.csrf_token;
      return result;
    })().catch((error) => {
      accessToken = null;
      csrfToken = null;
      throw error;
    }).finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

function rememberAuthResult(result) {
  if (result?.access_token) accessToken = result.access_token;
  if (result?.csrf_token) csrfToken = result.csrf_token;
  return result;
}

export const api = {
  setAccessToken: (token) => { accessToken = token || null; },
  clearAuth: () => { accessToken = null; csrfToken = null; },
  restoreSession: async () => {
    try {
      return rememberAuthResult(await refreshSession());
    } catch (error) {
      if (error.message.includes("401") || error.message.includes("session")) {
        accessToken = null;
        csrfToken = null;
        return null;
      }
      throw error;
    }
  },
  login: async (email, password, remember = true) =>
    rememberAuthResult(await request(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, remember }),
    })),
  register: async (name, email, password, remember = true) =>
    rememberAuthResult(await request(`${BASE}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, email, password, remember }),
    })),
  forgotPassword: (email) =>
    request(`${BASE}/auth/forgot-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    }),
  resetPassword: (token, newPassword) =>
    request(`${BASE}/auth/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, new_password: newPassword }),
    }),
  logout: async () => {
    try {
      if (csrfToken) {
        await request(`${BASE}/auth/logout`, {
          method: "POST",
          headers: { "X-CSRF-Token": csrfToken },
        });
      }
    } finally {
      accessToken = null;
      csrfToken = null;
    }
  },
  getMeta: () => request(`${BASE}/meta`),
  listings: (params) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, value]) => value !== undefined && value !== "")
    ).toString();
    return request(`${BASE}/listings?${qs}`);
  },

  predict: (payload) =>
    request(`${BASE}/predict`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  savePredictionHistory: (payload) =>
    request(`${BASE}/prediction-history`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  getPredictionHistory: (limit = 20) =>
    request(`${BASE}/prediction-history?limit=${encodeURIComponent(limit)}`),

  whatIf: (base, changes) =>
    request(`${BASE}/what-if`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base, changes }),
    }),

  compare: (params) => {
    const qs = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== "")
    ).toString();
    return request(`${BASE}/compare?${qs}`);
  },

  recommend: (prefs) =>
    request(`${BASE}/recommend`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(prefs),
    }),

  marketTrends: (city) =>
    request(`${BASE}/market-trends${city ? `?city=${encodeURIComponent(city)}` : ""}`),
};
