import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiClient, apiRequest, ApiClientError, getApiBaseUrl } from "../lib/apiClient";
import { authService } from "../services/authService";

describe("Frontend API Client (apiClient)", () => {
  beforeEach(() => {
    authService.clearSession();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("resolves base URL with fallback to default", () => {
    const url = getApiBaseUrl();
    expect(url).toBeDefined();
    expect(url).not.toMatch(/\/$/);
  });

  it("attaches Authorization header when user is authenticated", async () => {
    authService.setSession({ token: "test-valid-jwt-token-xyz" });

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ status: "ok" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await apiClient.get("/test-endpoint");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const calledHeaders = fetchMock.mock.calls[0][1].headers;
    expect(calledHeaders.get("Authorization")).toBe("Bearer test-valid-jwt-token-xyz");
  });

  it("does not attach Authorization header when user is not authenticated", async () => {
    authService.clearSession();

    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ status: "ok" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await apiClient.get("/public-endpoint");

    const calledHeaders = fetchMock.mock.calls[0][1].headers;
    expect(calledHeaders.has("Authorization")).toBe(false);
  });

  it("serializes JSON body for POST requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ id: "123" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const payload = { title: "Test Project", research_question: "What is this?" };
    await apiClient.post("/projects", payload);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toContain("/projects");
    expect(init.method).toBe("POST");
    expect(init.headers.get("Content-Type")).toBe("application/json");
    expect(JSON.parse(init.body)).toEqual(payload);
  });

  it("normalizes HTTP error responses with detail into ApiClientError", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ detail: "Research project was not found." }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiClient.get("/projects/nonexistent")).rejects.toThrow(
      "Research project was not found."
    );
  });

  it("handles 401 Unauthorized by clearing session and flagging isAuthError", async () => {
    authService.setSession({ token: "expired-jwt" });
    const clearSpy = vi.spyOn(authService, "handleUnauthorized");

    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ detail: "Token expired." }),
    });
    vi.stubGlobal("fetch", fetchMock);

    try {
      await apiClient.get("/projects");
      expect.fail("Should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiClientError);
      expect(err.status).toBe(401);
      expect(err.isAuthError).toBe(true);
      expect(clearSpy).toHaveBeenCalled();
    }
  });

  it("handles network failure gracefully", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("Failed to fetch")));

    try {
      await apiClient.get("/projects");
      expect.fail("Should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiClientError);
      expect(err.isNetworkError).toBe(true);
      expect(err.status).toBe(0);
    }
  });
});
