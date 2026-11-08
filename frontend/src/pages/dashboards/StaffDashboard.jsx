import Shell from "../../components/Shell";
import { Link } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";
import { useApi } from "./useApi";

export default function StaffDashboard() {
  const { profile } = useAuth();
  const { data, error, loading } = useApi("/dashboard/staff");
  const title = profile?.role === "authority" ? "Authority dashboard" : "Faculty dashboard";
  const isAuthority = profile?.role === "authority";
  return (
    <Shell title={title}>
      {isAuthority && <p><Link to="/authority/invitations">Invitations and registration approvals</Link></p>}
      {loading && <p role="status">Loading…</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {data && (
        <>
          <div className="grid">
            <Stat label="Open tickets" value={data.open_tickets} />
            <Stat label="Resolved" value={data.resolved_tickets} />
            <Stat label="Unassigned queue" value={data.unassigned_queue} />
            <Stat label="Assigned to me" value={data.assigned_to_me} />
            <Stat label="Drafts visible" value={data.drafts_visible} />
            <Stat label="Published visible" value={data.published_visible} />
          </div>
          {data.avg_first_response_hours !== null && (
            <p>Average first response: {data.avg_first_response_hours} hours</p>
          )}
          {data.by_department.length > 0 && (
            <table>
              <thead><tr><th>Department</th><th>Total</th><th>Resolved</th></tr></thead>
              <tbody>
                {data.by_department.map((row) => (
                  <tr key={row.department_id}><td>{row.name}</td><td>{row.total}</td><td>{row.resolved}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </Shell>
  );
}

function Stat({ label, value }) {
  return (
    <div className="stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}
