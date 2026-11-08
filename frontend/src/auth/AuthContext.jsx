import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { supabase } from "../lib/supabase";
import { fetchMe } from "../lib/api";

const AuthContext = createContext(null);

const NOT_SET_UP = "Your account is not set up yet. Contact your campus office.";

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);
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
      setProfileError(err.status === 403 ? NOT_SET_UP : "We could not load your profile. Try again.");
      return null;
    }
  }, []);

  useEffect(() => {
    if (!supabase) {
      setLoading(false);
      return undefined;
    }
    let active = true;
    supabase.auth.getSession().then(async ({ data }) => {
      if (!active) return;
      setSession(data.session);
      await loadProfile(data.session?.access_token);
      if (active) setLoading(false);
    });
    const { data: subscription } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      loadProfile(nextSession?.access_token);
    });
    return () => {
      active = false;
      subscription.subscription.unsubscribe();
    };
  }, [loadProfile]);

  const value = useMemo(
    () => ({
      session,
      profile,
      profileError,
      loading,
      refreshProfile: async () => loadProfile((await supabase?.auth.getSession())?.data.session?.access_token),
      signOut: async () => {
        await supabase?.auth.signOut();
        setProfile(null);
      },
    }),
    [session, profile, profileError, loading, loadProfile],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
