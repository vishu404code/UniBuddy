import { useState } from "react";
import { Link } from "react-router-dom";
import AuthLayout from "./AuthLayout";
import GoogleSignIn from "../components/GoogleSignIn";
import { apiRequest } from "../lib/api";
import { config } from "../lib/config";

// Students request access with their Google account. The request waits for an authorized
// person to approve it. Nothing is granted here, and no role is chosen by the person.
export default function RegisterPage() {
  const [receipt, setReceipt] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function handleCredential(idToken) {
    setBusy(true);
    setError(null);
    try {
      const result = await apiRequest("/auth/google/access-request", {
        method: "POST",
        body: { id_token: idToken },
      });
      setReceipt(result.message ?? "Thanks. Your request is waiting for review.");
    } catch (err) {
      setError(err.message || "The request could not be sent. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title="Request Student access">
      <p className="hint">
        Sign in with the Google account you want to use. Your request is reviewed before you get access.
        Faculty, Authority and Management accounts are created only by an authorized invitation.
      </p>
      {!receipt && <GoogleSignIn clientId={config.googleClientId} onCredential={handleCredential} />}
      {busy && <p className="status">Sending your request…</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {receipt && <p role="status">{receipt}</p>}
      <p className="links">
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </AuthLayout>
  );
}
