import { useState } from "react";
import { Link } from "react-router-dom";
import AuthLayout from "./AuthLayout";
import { supabase, supabaseConfigured } from "../lib/supabase";

const RECEIPT = "If an account exists for this address, a reset link has been sent. Check your inbox.";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!supabaseConfigured) return setError("Sign-in is not configured for this environment.");
    setBusy(true);
    setError(null);
    // The same message is shown whether or not the address has an account.
    await supabase.auth.resetPasswordForEmail(email.trim().toLowerCase(), {
      redirectTo: `${window.location.origin}/accept-invitation`,
    });
    setBusy(false);
    setSent(true);
  }

  return (
    <AuthLayout title="Reset your password">
      {sent ? (
        <p role="status">{RECEIPT}</p>
      ) : (
        <form onSubmit={handleSubmit} className="stack">
          <label>
            University email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          {error && <p role="alert" className="error">{error}</p>}
          <button type="submit" disabled={busy}>{busy ? "Sending…" : "Send reset link"}</button>
        </form>
      )}
      <p className="links"><Link to="/login">Back to sign in</Link></p>
    </AuthLayout>
  );
}
