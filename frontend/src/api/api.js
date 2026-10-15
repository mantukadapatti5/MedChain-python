const BASE_URL = "/api";

function getToken() {
  return sessionStorage.getItem("medchain_token");
}

async function request(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }

  let res;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (networkErr) {
    throw new Error(
      "Cannot reach the API server. Make sure the backend is running on port 5000."
    );
  }

  let data = null;
  const text = await res.text();
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }

  if (!res.ok) {
    // FastAPI sends errors as { detail: "..." } (or a list of validation errors);
    // the old Express backend used { error: "..." }. Support both so the real
    // message (e.g. "Drug is not available in the Vendor inventory list") is shown.
    let message = null;
    if (data) {
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail)) message = data.detail.map((d) => d.msg).filter(Boolean).join("; ");
      else if (typeof data.error === "string") message = data.error;
    }
    message = message || `Request failed with status ${res.status}`;
    const error = new Error(message);
    error.status = res.status;
    throw error;
  }

  return data;
}

export const api = {
  get: (path) => request(path, { method: "GET" }),
  post: (path, body) => request(path, { method: "POST", body }),
  put: (path, body) => request(path, { method: "PUT", body }),
  patch: (path, body) => request(path, { method: "PATCH", body }),
  delete: (path) => request(path, { method: "DELETE" }),
  login: (payload) => request("/auth/login", { method: "POST", body: payload, auth: false }),
};

export { getToken };
