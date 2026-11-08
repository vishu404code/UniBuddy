import Shell from "../../components/Shell";
import { useApi } from "./useApi";

export default function ManagementDashboard() {
  const { data, error, loading } = useApi("/management/stats");
  return (
    <Shell title="Management dashboard">
      <p className="hint">Aggregates only. Individual records are not shown here.</p>
      {loading && <p role="status">Loading…</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {data && (
        <>
          <div className="grid">
            <div className="stat"><span className="stat-value">{data.total_tickets}</span><span className="stat-label">Total tickets</span></div>
            <div className="stat"><span className="stat-value">{data.resolved_tickets}</span><span className="stat-label">Resolved</span></div>
            <div className="stat"><span className="stat-value">{data.resolution_rate ?? "—"}</span><span className="stat-label">Resolution rate</span></div>
          </div>
          <h2>By campus</h2>
          <Table rows={data.campuses} />
          <h2>By department</h2>
          <Table rows={data.departments} />
        </>
      )}
    </Shell>
  );
}

function Table({ rows }) {
  if (!rows?.length) return <p>No data yet.</p>;
  return (
    <table>
      <thead><tr><th>Name</th><th>Total</th><th>Resolved</th><th>Rate</th><th>Avg first response (h)</th></tr></thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id}>
            <td>{row.name}</td><td>{row.total_tickets}</td><td>{row.resolved_tickets}</td>
            <td>{row.resolution_rate ?? "—"}</td><td>{row.avg_first_response_hours ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
