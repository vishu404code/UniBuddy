import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import Shell from "../../components/Shell";
import TicketDetail from "../../components/TicketDetail";
import { useAuth } from "../../auth/AuthContext";
import { TICKET_STATUS_LABEL, formatDate } from "../../lib/format";
import { authedRequest } from "../../lib/session";

// Staff list: faculty and authority. RLS limits faculty to assigned tickets and their department queue.
export function StaffTicketsPage({ basePath }) {
  const [assigned, setAssigned] = useState("");
  const [status, setStatus] = useState("");
  const [tickets, setTickets] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const params = new URLSearchParams({ limit: "50" });
    if (assigned) params.set("assigned", assigned);
    if (status) params.set("status", status);
    setTickets(null);
    authedRequest(`/tickets?${params}`)
      .then((page) => setTickets(page.items))
      .catch((err) => setError(err.message));
  }, [assigned, status]);

  return (
    <Shell title="Tickets">
      <div className="row filters">
        <label>
          Show
          <select value={assigned} onChange={(e) => setAssigned(e.target.value)}>
            <option value="">All I can see</option>
            <option value="me">Assigned to me</option>
            <option value="unassigned">Unassigned</option>
          </select>
        </label>
        <label>
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">Any</option>
            {Object.entries(TICKET_STATUS_LABEL).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
      </div>
      {error && <p role="alert" className="error">{error}</p>}
      {!tickets && !error && <p role="status">Loading…</p>}
      {tickets && tickets.length === 0 && <p>No tickets match.</p>}
      {tickets && tickets.length > 0 && (
        <table>
          <thead><tr><th>Ticket</th><th>Question</th><th>Priority</th><th>Status</th><th>Updated</th></tr></thead>
          <tbody>
            {tickets.map((t) => (
              <tr key={t.id}>
                <td><Link to={`${basePath}/${t.id}`}>{t.ticket_number}</Link></td>
                <td>{t.subject}</td>
                <td>{t.priority}</td>
                <td>{TICKET_STATUS_LABEL[t.status]}</td>
                <td>{formatDate(t.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Shell>
  );
}

// Student list: only the student's own tickets (RLS).
export function MyTicketsPage({ basePath }) {
  const [tickets, setTickets] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    authedRequest("/tickets?limit=50")
      .then((page) => setTickets(page.items))
      .catch((err) => setError(err.message));
  }, []);

  return (
    <Shell title="My tickets" links={[{ to: "/student/chat", label: "Ask UniBuddy" }]}>
      {error && <p role="alert" className="error">{error}</p>}
      {!tickets && !error && <p role="status">Loading…</p>}
      {tickets && tickets.length === 0 && <p>You have not sent any questions to faculty yet.</p>}
      {tickets && tickets.length > 0 && (
        <table>
          <thead><tr><th>Ticket</th><th>Question</th><th>Status</th><th>Updated</th></tr></thead>
          <tbody>
            {tickets.map((t) => (
              <tr key={t.id}>
                <td><Link to={`${basePath}/${t.id}`}>{t.ticket_number}</Link></td>
                <td>{t.subject}</td>
                <td>{TICKET_STATUS_LABEL[t.status]}</td>
                <td>{formatDate(t.updated_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Shell>
  );
}

export function TicketDetailPage({ backTo }) {
  const { id } = useParams();
  const { profile } = useAuth();
  const canManage = profile?.role === "faculty" || profile?.role === "authority";
  return (
    <Shell title="Ticket" links={[{ to: backTo, label: "Back to tickets" }]}>
      <TicketDetail ticketId={id} canManage={canManage} />
    </Shell>
  );
}
