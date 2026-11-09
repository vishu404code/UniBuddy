import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import AuthLayout from "./AuthLayout";
import { supabase, supabaseConfigured } from "../lib/supabase";

const ALLOWED_TYPES = new Set(["invite", "recovery"]);
const INVALID = "This link is invalid, expired, or has already been used.";

// Verifies the single-use token from the email link, then hands over to /set-password.
export default function AcceptInvitationPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [error, setError] = useState(null);
  const attempted = useRef(false);

  useEffect(() => {
    // React runs effects twice in development. The token is single-use, so verify only once.
    if (attempted.current) return;
    attempted.current = true;

    const tokenHash = params.get("token_hash");
    const type = params.get("type");
    if (!supabaseConfigured) return setError("Sign-in is not configured for this environment.");
    if (!tokenHash || !ALLOWED_TYPES.has(type)) return setError(INVALID);

    supabase.auth.verifyOtp({ token_hash: tokenHash, type }).then(({ error: verifyError }) => {
      if (verifyError) return setError(INVALID);
      navigate("/set-password", { replace: true });
    });
  }, [params, navigate]);

  return (
    <AuthLayout title="Activate your account">
      {error ? (
        <>
          <p role="alert" className="error">{error}</p>
          <p className="hint">Ask your campus office for a new invitation, or use Forgot password.</p>
        </>
      ) : (
        <p role="status">Checking your link…</p>
      )}
      <p className="links"><Link to="/login">Back to sign in</Link></p>
    </AuthLayout>
  );
}
