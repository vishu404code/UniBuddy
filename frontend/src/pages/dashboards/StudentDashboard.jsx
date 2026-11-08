import Shell from "../../components/Shell";
import { useApi } from "./useApi";

const LINKS = [
  { to: "/student/chat", label: "Ask UniBuddy" },
  { to: "/student/tickets", label: "My tickets" },
];

export default function StudentDashboard() {
  const { data, error, loading } = useApi("/dashboard/student");
  return (
    <Shell title="Your dashboard" links={LINKS}>
      {loading && <p role="status">Loading…</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {data && (
        <div className="grid">
          <Stat label="Questions asked" value={data.total_questions} />
          <Stat label="Tickets" value={data.total_tickets} />
          {Object.entries(data.tickets_by_status).map(([status, count]) => (
            <Stat key={status} label={status.replace("_", " ")} value={count} />
          ))}
        </div>
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
