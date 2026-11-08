import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import AuthLayout from "./AuthLayout";
import { useAuth } from "../auth/AuthContext";
import { supabase } from "../lib/supabase";
import { dashboardPathForRole } from "../lib/roles";
import { passwordProblem } from "../lib/validation";

export default function SetPasswordPage() {
  const { session, loading, refreshProfile } = useAuth();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  if (loading) return <AuthLayout title="Set your password"><p role="status">Loading…</p></AuthLayout>;
  if (!session) {
    return (
      <AuthLayout title="Set your password">
        <p role="alert" className="error">Open the link from your invitation or reset email first.</p>
        <p className="links"><Link to="/login">Back to sign in</Link></p>
      </AuthLayout>
    );
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const problem = passwordProblem(password, confirmation);
    if (problem) return setError(problem);
    setBusy(true);
    setError(null);
    const { error: updateError } = await supabase.auth.updateUser({ password });
    if (updateError) {
      setBusy(false);
      return setError("Your password could not be set. Check the requirements and try again.");
    }
    const me = await refreshProfile();
    setBusy(false);
    const home = me && dashboardPathForRole(me.role);
    if (home) navigate(home, { replace: true });
    else setError("Your password is set, but your account is not ready yet. Contact your campus office.");
  }

  return (
    <AuthLayout title="Set your password">
      <form onSubmit={handleSubmit} className="stack">
        <label>
          New password
          <input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        <label>
          Confirm password
          <input type="password" autoComplete="new-password" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} required />
        </label>
        {error && <p role="alert" className="error">{error}</p>}
        <button type="submit" disabled={busy}>{busy ? "Saving…" : "Save password"}</button>
      </form>
    </AuthLayout>
  );
}
