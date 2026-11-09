import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import AuthLayout from "./AuthLayout";
import GoogleSignIn from "../components/GoogleSignIn";
import { useAuth } from "../auth/AuthContext";
import { apiRequest } from "../lib/api";
import { config } from "../lib/config";
import { destinationAfterSignIn } from "../lib/accessDecision";
import { dashboardPathForRole } from "../lib/roles";

export default function LoginPage() {
  const { session, profile, signInWithToken } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [credential, setCredential] = useState(null);
  const [needsAccess, setNeedsAccess] = useState(false);
  const [receipt, setReceipt] = useState(null);

  if (session && profile && dashboardPathForRole(profile.role)) {
    return <Navigate to={dashboardPathForRole(profile.role)} replace />;
  }

  async function handleCredential(idToken) {
    setBusy(true);
    setError(null);
    setReceipt(null);
    setNeedsAccess(false);
    setCredential(idToken);
    try {
      const { access_token: accessToken } = await apiRequest("/auth/google", {
        method: "POST",
        body: { id_token: idToken },
      });
      const me = await signInWithToken(accessToken);
      const destination = destinationAfterSignIn(me);
      if (destination.kind === "dashboard") {
        navigate(destination.path, { replace: true });
      } else {
        setError("Your account is not set up yet. Contact your campus office.");
      }
    } catch (err) {
      setNeedsAccess(err.code === "no_profile");
      setError(err.message || "Sign-in did not complete. Try again.");
    } finally {
      setBusy(false);
    }
  }

  async function requestAccess() {
    if (!credential) return;
    setBusy(true);
    setError(null);
    try {
      const result = await apiRequest("/auth/google/access-request", {
        method: "POST",
        body: { id_token: credential },
      });
      setReceipt(result.message ?? "Thanks. Your request is waiting for review.");
    } catch (err) {
      setError(err.message || "The request could not be sent. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title="Sign in">
      <p className="hint">Sign in with your Google account.</p>
      <GoogleSignIn clientId={config.googleClientId} onCredential={handleCredential} />
      {busy && <p className="status">Checking your account…</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {needsAccess && !receipt && (
        <button type="button" className="secondary" onClick={requestAccess} disabled={busy}>
          Request Student access
        </button>
      )}
      {receipt && <p role="status">{receipt}</p>}
      <p className="links">
        New to UniBuddy? <Link to="/register">Learn about requesting access</Link>
      </p>
    </AuthLayout>
  );
}
