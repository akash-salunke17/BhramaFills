/**
 * Authentication service managing user session, Supabase JWT tokens, and login states.
 */

const AUTH_STORAGE_KEY = "bharmafills_auth_session_v1";

// In-memory fallback if localStorage is unavailable or blocked
let inMemorySession = null;
const authListeners = new Set();

function notifyAuthListeners() {
  authListeners.forEach((listener) => {
    try {
      listener(authService.getSession());
    } catch (err) {
      console.error("[authService] Listener notification error:", err);
    }
  });
}

function getStorage() {
  try {
    if (typeof window !== "undefined" && window.localStorage) {
      return window.localStorage;
    }
  } catch {
    // Restricted environment
  }
  return null;
}

function readSessionFromStorage() {
  const storage = getStorage();
  if (storage) {
    try {
      const raw = storage.getItem(AUTH_STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (parsed && typeof parsed === "object" && parsed.token) {
        // Check expiration if recorded
        if (parsed.expiresAt && Date.now() > parsed.expiresAt) {
          storage.removeItem(AUTH_STORAGE_KEY);
          return null;
        }
        return parsed;
      }
    } catch (err) {
      console.warn("[authService] Corrupted session in storage, resetting:", err);
      try {
        storage.removeItem(AUTH_STORAGE_KEY);
      } catch {
        // Ignore
      }
    }
  }
  return inMemorySession;
}

function writeSessionToStorage(session) {
  inMemorySession = session;
  const storage = getStorage();
  if (storage) {
    try {
      if (session) {
        storage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
      } else {
        storage.removeItem(AUTH_STORAGE_KEY);
      }
    } catch (err) {
      console.warn("[authService] Failed writing session to storage:", err);
    }
  }
}

export const authService = {
  /**
   * Subscribe to authentication state changes.
   */
  subscribe(callback) {
    if (typeof callback === "function") {
      authListeners.add(callback);
    }
    return () => authListeners.delete(callback);
  },

  /**
   * Retrieve current active session object { token, user, expiresAt } or null.
   */
  getSession() {
    return readSessionFromStorage();
  },

  /**
   * Get active Bearer token string or null.
   */
  getToken() {
    const session = this.getSession();
    return session?.token || null;
  },

  /**
   * Get current authenticated user object or null.
   */
  getUser() {
    const session = this.getSession();
    return session?.user || null;
  },

  /**
   * Check if current session exists and is unexpired.
   */
  isAuthenticated() {
    const session = this.getSession();
    return Boolean(session && session.token);
  },

  /**
   * Set session data.
   */
  setSession({ token, user, expiresAt = null }) {
    if (!token || typeof token !== "string") {
      throw new Error("A valid JWT string is required for authentication.");
    }
    const sessionData = {
      token: token.trim(),
      user: user || {
        id: "demo-user",
        email: "researcher@bharmafills.org",
        role: "authenticated",
        user_metadata: { full_name: "Research Fellow" },
      },
      expiresAt: expiresAt || (Date.now() + 7 * 24 * 60 * 60 * 1000), // 7 days default
    };
    writeSessionToStorage(sessionData);
    notifyAuthListeners();
    return sessionData;
  },

  /**
   * Clear active session (logout).
   */
  clearSession() {
    writeSessionToStorage(null);
    notifyAuthListeners();
  },

  /**
   * Called when API returns 401 Unauthorized.
   */
  handleUnauthorized() {
    console.warn("[authService] 401 Unauthorized encountered. Session invalidated.");
    this.clearSession();
  },

  /**
   * Helper to login with a specific JWT (e.g. from Supabase Auth).
   */
  loginWithToken(token, user = null) {
    return this.setSession({ token, user });
  },

  /**
   * Helper to login with a demo session for offline / hackathon testing.
   */
  loginAsDemo(customUser = null) {
    const demoUser = customUser || {
      id: "00000000-0000-4000-a000-000000000001",
      email: "test.researcher@bharmafills.org",
      role: "authenticated",
      user_metadata: { full_name: "Lead Hackathon Researcher" },
    };

    // A mock token format for demo/testing
    const mockToken = `demo_jwt_${demoUser.id}_${Date.now()}`;
    return this.setSession({
      token: mockToken,
      user: demoUser,
    });
  },

  /**
   * Logout current user.
   */
  logout() {
    this.clearSession();
  },
};
