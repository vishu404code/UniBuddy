import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import AuthLayout from "./AuthLayout";
import { useAuth } from "../auth/AuthContext";
import { supabase, supabaseConfigured } from "../lib/supabase";
import { destinationAfterSignIn } from "../lib/accessDecision";
import { AUTH_CALLBACK_PATH } from "../lib/googleSignIn";

export default function AuthCallbackPage() {
  const { refreshProfile, signOut } = useAuth();
  const navigate = useNavigate();
  const [state, setState] = useState({ status: "working" });
  const started = useRef(false);

  useEffect(() => {
    // StrictMode runs effects twice in development, and a PKCE code can be used only once.
    if (started.current) return;
    started.current = true;

    async function complete() {
      if (!supabaseConfigured) {
        setState({ status: "error", message: "Sign-in is not configured for this environment." });
        return;
      }
      const params = new URLSearchParams(window.location.search);
      const code = params.get("code");
      const providerError = params.get("error_description") || params.get("error");
      // Drop the one-time code and any error from the address bar.
      window.history.replaceState({}, "", AUTH_CALLBACK_PATH);

      if (providerError || !code) {
        setState({ status: "error", message: "Google sign-in was cancelled or did not complete. Try again." });
        return;
      }
      const { error } = await supabase.auth.exchangeCodeForSession(code);
      if (error) {
        setState({ status: "error", message: "Google sign-in could not be completed. Try again." });
        return;
      }
      // The role comes only from the UniBuddy profile for this Auth user ID.
      const me = await refreshProfile();
      const destination = destinationAfterSignIn(me);
      if (destination.kind === "dashboard") {
        navigate(destination.path, { replace: true });
      } else {
        setState({ status: "no_access" });
      }
    }

    complete();
  }, [navigate, refreshProfile]);

  if (state.status === "working") {
    return (
      <AuthLayout title="Signing you in">
        <p className="status">Please wait…</p>
      </AuthLayout>
    );
  }

  if (state.status === "error") {
    return (
      <AuthLayout title="Sign in">
        <p role="alert" className="error">{state.message}</p>
        <p className="links"><Link to="/login">Back to sign in</Link></p>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Account not set up">
      <p role="alert" className="error">
        Your Google account signed in, but UniBuddy has no account for it. Contact your campus office.
        Students can <Link to="/register">request access</Link>; access is granted only after approval.
      </p>
      <button
        type="button"
        onClick={async () => {
          await signOut();
          navigate("/login", { replace: true });
        }}
      >
        Sign out
      </button>
    </AuthLayout>
  );
}
