import { describe, it, expect, beforeEach, vi } from "vitest";
import { authService } from "../services/authService";

describe("Frontend Authentication Service (authService)", () => {
  beforeEach(() => {
    authService.clearSession();
  });

  it("reports unauthenticated by default", () => {
    expect(authService.isAuthenticated()).toBe(false);
    expect(authService.getToken()).toBeNull();
    expect(authService.getUser()).toBeNull();
  });

  it("stores and retrieves active session", () => {
    const session = authService.setSession({
      token: "test-token-123",
      user: { id: "user-1", email: "user@example.com" },
    });

    expect(authService.isAuthenticated()).toBe(true);
    expect(authService.getToken()).toBe("test-token-123");
    expect(authService.getUser()?.email).toBe("user@example.com");
    expect(session.token).toBe("test-token-123");
  });

  it("clears session on logout", () => {
    authService.setSession({ token: "test-token" });
    expect(authService.isAuthenticated()).toBe(true);

    authService.logout();
    expect(authService.isAuthenticated()).toBe(false);
    expect(authService.getToken()).toBeNull();
  });

  it("logs in with demo researcher credentials", () => {
    const session = authService.loginAsDemo();
    expect(session.token).toContain("demo_jwt");
    expect(session.user.email).toBe("test.researcher@bharmafills.org");
    expect(authService.isAuthenticated()).toBe(true);
  });

  it("notifies listeners upon session updates", () => {
    const listener = vi.fn();
    const unsubscribe = authService.subscribe(listener);

    authService.setSession({ token: "token-a" });
    expect(listener).toHaveBeenCalledTimes(1);

    authService.clearSession();
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
    authService.setSession({ token: "token-b" });
    expect(listener).toHaveBeenCalledTimes(2);
  });
});
