import { useEffect, useState } from "react";
import Shell from "../../components/Shell";
import { authedRequest } from "../../lib/session";
import { ApiError } from "../../lib/api";
import { isEmailAddress } from "../../lib/validation";

export default function SuperAdminAccountsPage() {
  return (
    <Shell title="Account management">
      <p className="hint">
        Super Admin provisions authority and management accounts. It does not read academic records.
      </p>
      <InviteAccountForm />
      <AccountList />
    </Shell>
  );
}

function InviteAccountForm() {
  const [role, setRole] = useState("authority");
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [campusId, setCampusId] = useState("");
  const [campuses, setCampuses] = useState([]);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    authedRequest("/provisioning/campuses")
      .then(setCampuses)
      .catch((err) => setError(err.message));
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    if (!isEmailAddress(email)) {
      setError("Use an address on the university domain.");
      return;
    }
    if (role === "authority" && !campusId) {
      setError("Choose the campus for this authority account.");
      return;
    }
    setBusy(true);
    try {
      const body = { email: email.trim(), full_name: fullName.trim(), campus_id: campusId || null };
      await authedRequest(`/provisioning/${role}`, { method: "POST", body });
      setMessage(`Invitation sent to ${email.trim()}. The link expires in 24 hours.`);
      setEmail("");
      setFullName("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The invitation could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>Invite an account</h2>
      <form onSubmit={handleSubmit} className="stack">
        <label>
          Role
          <select value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="authority">Authority</option>
            <option value="management">Management</option>
          </select>
        </label>
        <label>
          Full name
          <input value={fullName} onChange={(e) => setFullName(e.target.value)} required minLength={2} maxLength={120} />
        </label>
        <label>
          University email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        <label>
          Campus {role === "authority" ? "" : "(optional)"}
          <select value={campusId} onChange={(e) => setCampusId(e.target.value)}>
            <option value="">{role === "authority" ? "Choose a campus" : "No campus"}</option>
            {campuses.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        {error && <p role="alert" className="error">{error}</p>}
        {message && <p role="status">{message}</p>}
        <button type="submit" disabled={busy}>{busy ? "Sending…" : "Send invitation"}</button>
      </form>
    </section>
  );
}

function AccountList() {
  const [accounts, setAccounts] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    authedRequest("/admin/accounts")
      .then(setAccounts)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <section className="card">
      <h2>Accounts</h2>
      {error && <p role="alert" className="error">{error}</p>}
      <table>
        <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Campus</th></tr></thead>
        <tbody>
          {accounts.map((a) => (
            <tr key={a.id}>
              <td>{a.full_name ?? "—"}</td><td>{a.email}</td><td>{a.role}</td><td>{a.campus_name ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
