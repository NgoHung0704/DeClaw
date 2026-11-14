// API base helpers. The REST and WebSocket base URLs derive from
// window.location — the port is configurable, so nothing anywhere in this
// UI may write the default port literal (spec section 13).

export const httpBase = () =>
  `${window.location.protocol}//${window.location.host}`;

export const wsBase = () =>
  `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

const massageError = async (response) => {
  try {
    const body = await response.json();
    const wrapped = body && body.error;
    if (wrapped && typeof wrapped.code === "string") {
      return new ApiError(response.status, wrapped.code, wrapped.message || wrapped.code);
    }
  } catch (_) {
    // malformed body: fall through to the generic shape
  }
  return new ApiError(response.status, "http_error", `HTTP ${response.status}`);
};

const requestResponse = async (method, path, body) => {
  const options = { method, credentials: "same-origin" };
  if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  const response = await fetch(`${httpBase()}${path}`, options);
  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent("declaw:unauthenticated"));
    throw new ApiError(401, "unauthorized", "Authentication required");
  }
  if (!response.ok) {
    throw await massageError(response);
  }
  return response;
};

const request = async (method, path, body) => (await requestResponse(method, path, body)).json();

// Preflight uses the same auth/error handling; the native browser performs the
// attachment request itself so downloads never navigate to a blob origin.
export const prepareDownload = async (path) => {
  const response = await requestResponse("GET", path);
  await response.body?.cancel();
  return `${httpBase()}${path}`;
};

export const getJson = (path) => request("GET", path);
export const postJson = (path, body) => request("POST", path, body ?? {});
export const putJson = (path, body) => request("PUT", path, body);
