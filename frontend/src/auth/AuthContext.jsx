import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { fetchMe } from "../lib/api";
import { clearSessionToken, getSessionToken, setSessionToken } from "../lib/session";

const AuthContext = createContext(null);

const NOT_SET_UP = "Your account is not set up yet. Contact your campus office.";

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => getSessionToken());
  const [profile, setProfile] = useState(null);
  const [profileError, setProfileError] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadProfile = useCallback(async (accessToken) => {
    if (!accessToken) {
      setProfile(null);
      setProfileError(null);
      return null;
    }
    try {
      const me = await fetchMe(accessToken);
      setProfile(me);
      setProfileError(null);
      return me;
    } catch (err) {
      setProfile(null);
      if (err.status === 401) {
        // The session has expired or was revoked. Ask the person to sign in again.
        clearSessionToken();
        setToken(null);
        setProfileError("Your session has ended. Sign in again.");
      } else {
        setProfileError(err.status === 403 ? NOT_SET_UP : "We could not load your profile. Try again.");
      }
      return null;
    }
  }, []);

  useEffect(() => {
    let active = true;
    loadProfile(getSessionToken()).finally(() => {
      if (active) setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [loadProfile]);

  const value = useMemo(
    () => ({
      session: token ? { access_token: token } : null,
      profile,
      profileError,
      loading,
      // Stores the token from a successful Google sign-in and loads the profile it belongs to.
      signInWithToken: async (accessToken) => {
        setSessionToken(accessToken);
        setToken(accessToken);
        return loadProfile(accessToken);
      },
      refreshProfile: async () => loadProfile(getSessionToken()),
      signOut: async () => {
        clearSessionToken();
        setToken(null);
        setProfile(null);
        setProfileError(null);
      },
    }),
    [token, profile, profileError, loading, loadProfile],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
