/**
 * Centralized HTTP API client with JWT attachment, timeout resilience, and error normalization.
 */

import { authService } from "../services/authService";

const DEFAULT_TIMEOUT_MS = 30000;

export class ApiClientError extends Error {
  constructor(message, { status = 0, detail = null, data = null, isTimeout = false, isNetworkError = false } = {}) {
    super(message);
    this.name = "ApiClientError";
    this.status = status;
    this.detail = detail;
    this.data = data;
    this.isTimeout = isTimeout;
    this.isNetworkError = isNetworkError;
    this.isAuthError = status === 401;
    this.isNotFoundError = status === 404;
  }
}

export function getApiBaseUrl() {
  const envUrl = typeof import.meta !== "undefined" && import.meta.env?.VITE_API_BASE_URL;
  if (envUrl && typeof envUrl === "string") {
    return envUrl.replace(/\/+$/, "");
  }
  return "http://localhost:8000/api/v1";
}

/**
 * Core request execution wrapper.
 */
export async function apiRequest(endpoint, {
  method = "GET",
  params = null,
  body = null,
  headers = {},
  token = null,
  timeoutMs = DEFAULT_TIMEOUT_MS,
  signal = null,
} = {}) {
  const baseUrl = getApiBaseUrl();
  const normalizedEndpoint = endpoint.startsWith("/") ? endpoint : `/${endpoint}`;
  let url = `${baseUrl}${normalizedEndpoint}`;

  // Append query parameters if present
  if (params && typeof params === "object") {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, val]) => {
      if (val !== undefined && val !== null && val !== "") {
        searchParams.append(key, String(val));
      }
    });
    const qs = searchParams.toString();
    if (qs) {
      url += (url.includes("?") ? "&" : "?") + qs;
    }
  }

  // Construct request headers
  const requestHeaders = new Headers(headers);

  // Attach auth token if available and not explicitly provided as false
  const activeToken = token !== undefined && token !== null ? token : authService.getToken();
  if (activeToken && !requestHeaders.has("Authorization")) {
    requestHeaders.set("Authorization", `Bearer ${activeToken.trim()}`);
  }

  // Handle JSON body serialization
  let formattedBody = body;
  if (body !== null && body !== undefined && !(body instanceof FormData) && !(body instanceof Blob)) {
    if (!requestHeaders.has("Content-Type")) {
      requestHeaders.set("Content-Type", "application/json");
    }
    formattedBody = JSON.stringify(body);
  }

  // Setup abort controller for timeout handling
  const controller = new AbortController();
  const combinedSignal = signal || controller.signal;
  let timerId = null;

  if (timeoutMs > 0) {
    timerId = setTimeout(() => {
      controller.abort();
    }, timeoutMs);
  }

  try {
    const response = await fetch(url, {
      method,
      headers: requestHeaders,
      body: formattedBody,
      signal: combinedSignal,
    });

    if (timerId) clearTimeout(timerId);

    // Parse response body
    let responseData = null;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      try {
        responseData = await response.json();
      } catch {
        responseData = null;
      }
    } else {
      try {
        responseData = await response.text();
      } catch {
        responseData = null;
      }
    }

    if (!response.ok) {
      let errorMessage = `Request failed with status ${response.status}`;
      let errorDetail = null;

      if (responseData && typeof responseData === "object") {
        if (typeof responseData.detail === "string") {
          errorMessage = responseData.detail;
          errorDetail = responseData.detail;
        } else if (Array.isArray(responseData.detail)) {
          // Pydantic validation error list
          errorMessage = responseData.detail.map((d) => d.msg || d.message || JSON.stringify(d)).join("; ");
          errorDetail = responseData.detail;
        } else if (responseData.message) {
          errorMessage = responseData.message;
        }
      }

      // Automatically inform authService if token is expired/invalid
      if (response.status === 401) {
        authService.handleUnauthorized();
      }

      throw new ApiClientError(errorMessage, {
        status: response.status,
        detail: errorDetail,
        data: responseData,
      });
    }

    return responseData;
  } catch (err) {
    if (timerId) clearTimeout(timerId);

    if (err instanceof ApiClientError) {
      throw err;
    }

    const isAbort = err.name === "AbortError" || combinedSignal.aborted;
    if (isAbort) {
      throw new ApiClientError("Request timed out. Please check backend connectivity.", {
        status: 0,
        isTimeout: true,
      });
    }

    throw new ApiClientError(err.message || "Network error. Failed to reach the backend service.", {
      status: 0,
      isNetworkError: true,
    });
  }
}

export const apiClient = {
  get: (endpoint, options = {}) => apiRequest(endpoint, { ...options, method: "GET" }),
  post: (endpoint, body, options = {}) => apiRequest(endpoint, { ...options, method: "POST", body }),
  patch: (endpoint, body, options = {}) => apiRequest(endpoint, { ...options, method: "PATCH", body }),
  put: (endpoint, body, options = {}) => apiRequest(endpoint, { ...options, method: "PUT", body }),
  delete: (endpoint, options = {}) => apiRequest(endpoint, { ...options, method: "DELETE" }),
};
