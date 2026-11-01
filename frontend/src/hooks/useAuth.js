import { useState, useEffect } from "react";
import { authService } from "../services/authService";

export function useAuth() {
  const [session, setSession] = useState(() => authService.getSession());
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const unsubscribe = authService.subscribe((updatedSession) => {
      setSession(updatedSession);
    });
    return unsubscribe;
  }, []);

  const loginWithToken = (token, user = null) => {
    setLoading(true);
    try {
      return authService.loginWithToken(token, user);
    } finally {
      setLoading(false);
    }
  };

  const loginAsDemo = (customUser = null) => {
    setLoading(true);
    try {
      return authService.loginAsDemo(customUser);
    } finally {
      setLoading(false);
    }
  };

  const logout = () => {
    authService.logout();
  };

  return {
    session,
    user: session?.user || null,
    token: session?.token || null,
    isAuthenticated: Boolean(session && session.token),
    loading,
    loginWithToken,
    loginAsDemo,
    logout,
  };
}
