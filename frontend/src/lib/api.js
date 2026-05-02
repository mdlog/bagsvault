// Lightweight axios wrapper used by the BagsVault frontend.
//
// The backend returns structured errors of the shape:
//   { error: { code, message, details } }
//
// We unwrap that envelope and rethrow a plain `Error` whose `.message`
// is the human-readable message and `.code` / `.details` carry the
// structured fields. Callers (toast.error, page-level handlers) only
// need to read `err.message` to surface a useful string.
//
// Base URL precedence:
//   1. `process.env.REACT_APP_BACKEND_URL` — set in the create-react-app
//      env at build time (CRA only inlines REACT_APP_*).
//   2. Fallback: empty string → relative URLs against the same origin
//      (works when the frontend is served by FastAPI in production).

import axios from "axios";

const BASE_URL = (process.env.REACT_APP_BACKEND_URL || "").replace(/\/$/, "");

const client = axios.create({
  baseURL: BASE_URL || undefined,
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
});

function normaliseError(err) {
  // Axios attaches the parsed response body at err.response.data.
  // FastAPI always returns 4xx/5xx as JSON because we registered a
  // custom exception handler in backend/app/exceptions.py.
  const body = err?.response?.data;
  if (body && typeof body === "object" && body.error) {
    const wrapped = new Error(body.error.message || "Request failed");
    wrapped.code = body.error.code || "unknown_error";
    wrapped.details = body.error.details || {};
    wrapped.status = err?.response?.status;
    return wrapped;
  }
  // Network failure / timeout / non-FastAPI body.
  const msg = err?.message || "Network error";
  const wrapped = new Error(msg);
  wrapped.code = err?.code || "network_error";
  wrapped.status = err?.response?.status;
  return wrapped;
}

export async function apiGet(path, config = {}) {
  try {
    const resp = await client.get(path, config);
    return resp.data;
  } catch (err) {
    throw normaliseError(err);
  }
}

export async function apiPost(path, body = {}, config = {}) {
  try {
    const resp = await client.post(path, body, config);
    return resp.data;
  } catch (err) {
    throw normaliseError(err);
  }
}

export const apiClient = client;
export const apiBaseUrl = BASE_URL;
