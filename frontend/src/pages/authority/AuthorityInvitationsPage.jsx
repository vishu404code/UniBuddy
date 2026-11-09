import { useEffect, useState } from "react";
import Shell from "../../components/Shell";
import { authedRequest } from "../../lib/session";
import { ApiError } from "../../lib/api";
import { isEmailAddress } from "../../lib/validation";

const LINKS = [{ to: "/authority/dashboard", label: "Dashboard" }];

export default function AuthorityInvitationsPage() {
  return (
    <Shell title="Invitations and approvals" links={LINKS}>
      <InviteForm role="student" title="Invite a student" />
      <InviteForm role="faculty" title="Invite a faculty member" needsDepartment />
      <PendingRegistrations />
    </Shell>
  );
}

function InviteForm({ role, title, needsDepartment = false }) {
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [departments, setDepartments] = useState([]);
  const [message, setMessage] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!needsDepartment) return;
    authedRequest("/provisioning/departments")
      .then(setDepartments)
      .catch((err) => setError(err.message));
  }, [needsDepartment]);

  async function handleSubmit(event) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    if (!isEmailAddress(email)) {
      setError("Use an address on the university domain.");
      return;
    }
    setBusy(true);
    try {
      const body = { email: email.trim(), full_name: fullName.trim() };
      if (needsDepartment) body.department_id = departmentId;
      await authedRequest(`/provisioning/${role}s`, { method: "POST", body });
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
      <h2>{title}</h2>
      <form onSubmit={handleSubmit} className="stack">
        <label>
          Full name
          <input value={fullName} onChange={(e) => setFullName(e.target.value)} required minLength={2} maxLength={120} />
        </label>
        <label>
          University email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </label>
        {needsDepartment && (
          <label>
            Department
            <select value={departmentId} onChange={(e) => setDepartmentId(e.target.value)} required>
              <option value="">Choose a department</option>
              {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </label>
        )}
        {error && <p role="alert" className="error">{error}</p>}
        {message && <p role="status">{message}</p>}
        <button type="submit" disabled={busy}>{busy ? "Sending…" : "Send invitation"}</button>
      </form>
    </section>
  );
}

function PendingRegistrations() {
  const [items, setItems] = useState([]);
  const [error, setError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    authedRequest("/provisioning/registrations")
      .then(setItems)
      .catch((err) => setError(err.message));
  }, [reloadKey]);

  async function decide(id, action) {
    setError(null);
    try {
      await authedRequest(`/provisioning/registrations/${id}/${action}`, {
        method: "POST",
        body: action === "reject" ? {} : undefined,
      });
      setReloadKey((k) => k + 1);
    } catch (err) {
      setError(err.message);
    }
  }

  return (
    <section className="card">
      <h2>Pending student registrations</h2>
      <p className="hint">Approving sends the student an invitation to your campus.</p>
      {error && <p role="alert" className="error">{error}</p>}
      {items.length === 0 ? (
        <p>No pending requests.</p>
      ) : (
        <table>
          <thead><tr><th>Name</th><th>Email</th><th>Requested</th><th /></tr></thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>{item.full_name}</td>
                <td>{item.email}</td>
                <td>{new Date(item.requested_at).toLocaleDateString()}</td>
                <td>
                  <button type="button" onClick={() => decide(item.id, "approve")}>Approve</button>{" "}
                  <button type="button" className="secondary" onClick={() => decide(item.id, "reject")}>Reject</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
