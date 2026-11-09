import { useState } from "react";
import { Link } from "react-router-dom";
import AuthLayout from "./AuthLayout";
import { submitRegistration } from "../lib/api";
import { UNIVERSITY_DOMAIN, isUniversityEmail } from "../lib/validation";

export default function RegisterPage() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [receipt, setReceipt] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setError(null);
    if (!isUniversityEmail(email)) {
      setError(`Use your university email address ending in @${UNIVERSITY_DOMAIN}.`);
      return;
    }
    setBusy(true);
    try {
      const result = await submitRegistration(email.trim(), fullName.trim());
      setReceipt(result.message);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title="Request student access">
      {receipt ? (
        <p role="status">{receipt}</p>
      ) : (
        <form onSubmit={handleSubmit} className="stack">
          <p className="hint">
            Registering does not grant access. You will get an invitation only after review.
          </p>
          <label>
            Full name
            <input value={fullName} onChange={(e) => setFullName(e.target.value)} required minLength={2} maxLength={120} />
          </label>
          <label>
            University email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          {error && <p role="alert" className="error">{error}</p>}
          <button type="submit" disabled={busy}>{busy ? "Sending…" : "Submit request"}</button>
        </form>
      )}
      <p className="links"><Link to="/login">Back to sign in</Link></p>
    </AuthLayout>
  );
}
