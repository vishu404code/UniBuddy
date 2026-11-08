import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import AuthLayout from "./AuthLayout";
import { useAuth } from "../auth/AuthContext";
import { supabase, supabaseConfigured } from "../lib/supabase";
import { dashboardPathForRole } from "../lib/roles";
import { googleSignInRequest } from "../lib/googleSignIn";

export default function LoginPage() {
  const { session, profile, refreshProfile } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  if (session && profile && dashboardPathForRole(profile.role)) {
    return <Navigate to={dashboardPathForRole(profile.role)} replace />;
  }

  async function handleGoogle() {
    if (!supabaseConfigured) return setError("Sign-in is not configured for this environment.");
    setError(null);
    const { error: oauthError } = await supabase.auth.signInWithOAuth(
      googleSignInRequest(window.location.origin),
    );
    if (oauthError) setError("Google sign-in is not available right now. Use your email and password.");
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!supabaseConfigured) return setError("Sign-in is not configured for this environment.");
    setBusy(true);
    setError(null);
    const { error: signInError } = await supabase.auth.signInWithPassword({
      email: email.trim().toLowerCase(),
      password,
    });
    if (signInError) {
      setBusy(false);
      setError("Email or password is incorrect.");
      return;
    }
    const me = await refreshProfile();
    setBusy(false);
    if (me && dashboardPathForRole(me.role)) {
      navigate(dashboardPathForRole(me.role), { replace: true });
    } else {
      setError("Your account is not set up yet. Contact your campus office.");
    }
  }

  return (
    <AuthLayout title="Sign in">
      <form onSubmit={handleSubmit} className="stack">
        <label>
          University email
          <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Password
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {error && <p role="alert" className="error">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      <p className="links">or</p>
      <button type="button" onClick={handleGoogle} disabled={busy}>Continue with Google</button>
      <p className="links">
        <Link to="/forgot-password">Forgot password?</Link> · <Link to="/register">Request access as a student</Link>
      </p>
    </AuthLayout>
  );
}
