// eslint-disable-next-line no-unused-vars
import React from "react";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import api, {
  clearAccessToken,
  getAccessToken,
  refreshAccessToken,
} from "../api/client";

const SessionContext = createContext(null);

export function SessionProvider({ children }) {
  const [principal, setPrincipal] = useState(null);
  const [status, setStatus] = useState("loading");

  const loadSession = useCallback(async () => {
    try {
      let token = getAccessToken();
      if (!token) {
        token = await refreshAccessToken();
      }

      const { data } = await api.get("/auth/me");
      setPrincipal(data);
      setStatus("authenticated");
      return data;
    } catch {
      clearAccessToken();
      setPrincipal(null);
      setStatus("anonymous");
      return null;
    }
  }, []);

  const clearSession = useCallback(() => {
    clearAccessToken();
    setPrincipal(null);
    setStatus("anonymous");
  }, []);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => {
      void loadSession();
    }, 0);
    return () => window.clearTimeout(timeoutId);
  }, [loadSession]);

  const value = useMemo(() => ({
    principal,
    status,
    refreshSession: loadSession,
    clearSession,
    hasRole: (role) => Boolean(principal?.roles?.includes(role)),
    hasPermission: (permission) => Boolean(principal?.permissions?.includes(permission)),
  }), [clearSession, loadSession, principal, status]);

  return (
    <SessionContext.Provider value={value}>
      {children}
    </SessionContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useSession() {
  const value = useContext(SessionContext);
  if (!value) {
    throw new Error("useSession must be used inside SessionProvider");
  }
  return value;
}
