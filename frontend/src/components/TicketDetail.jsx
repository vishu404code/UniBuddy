import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../lib/api";
import { authedRequest } from "../lib/session";
import { TICKET_STATUS_LABEL, formatDate } from "../lib/format";

// Status moves only forward. The server enforces it too; this only hides impossible choices.
const NEXT_STATUSES = {
  submitted: ["assigned", "in_progress", "resolved"],
  assigned: ["in_progress", "resolved"],
  in_progress: ["resolved"],
  resolved: [],
};

export default function TicketDetail({ ticketId, canManage }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [reply, setReply] = useState("");
  const [nextStatus, setNextStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);

  const load = useCallback(async () => {
    try {
      setData(await authedRequest(`/tickets/${ticketId}`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "This ticket could not be loaded.");
    }
  }, [ticketId]);

  useEffect(() => { load(); }, [load]);

  async function change(body, message) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setData(await authedRequest(`/tickets/${ticketId}`, { method: "PATCH", body }));
      setNotice(message);
      setReply("");
      setNextStatus("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The change could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  if (error && !data) return <p role="alert" className="error">{error}</p>;
  if (!data) return <p role="status">Loading…</p>;

  const { ticket, events } = data;
  const options = NEXT_STATUSES[ticket.status] ?? [];
  const isTaken = Boolean(ticket.assigned_faculty_id);

  return (
    <div className="stack">
      <section className="card">
        <h2>{ticket.ticket_number}</h2>
        <p><strong>Status:</strong> {TICKET_STATUS_LABEL[ticket.status]} · <strong>Priority:</strong> {ticket.priority}</p>
        <p><strong>Question:</strong> {ticket.question}</p>
        {ticket.description && <p><strong>Details:</strong> {ticket.description}</p>}
        <p className="hint">Sent {formatDate(ticket.created_at)}</p>
      </section>

      <section className="card">
        <h3>Timeline</h3>
        {events.length === 0 && <p>No updates yet.</p>}
        <ol className="plain-list">
          {events.map((e) => (
            <li key={e.id}>
              <strong>{e.event_type.replace("_", " ")}</strong> · {formatDate(e.created_at)}
              {e.note && <div>{e.note}</div>}
            </li>
          ))}
        </ol>
      </section>

      {canManage && ticket.status !== "resolved" && (
        <section className="card stack">
          <h3>Respond</h3>
          {!isTaken && (
            <button type="button" disabled={busy} onClick={() => change({ take_ticket: true }, "You are now handling this ticket.")}>
              Take this ticket
            </button>
          )}
          <label>
            Reply to the student
            <textarea value={reply} onChange={(e) => setReply(e.target.value)} rows={3} maxLength={4000} />
          </label>
          <div className="row">
            <button type="button" disabled={busy || !reply.trim()} onClick={() => change({ reply: reply.trim() }, "Reply sent. The student has been notified.")}>
              Send reply
            </button>
          </div>
          {options.length > 0 && (
            <div className="row">
              <label>
                Change status
                <select value={nextStatus} onChange={(e) => setNextStatus(e.target.value)}>
                  <option value="">Keep as {TICKET_STATUS_LABEL[ticket.status]}</option>
                  {options.map((s) => <option key={s} value={s}>{TICKET_STATUS_LABEL[s]}</option>)}
                </select>
              </label>
              <button type="button" disabled={busy || !nextStatus} onClick={() => change({ status: nextStatus }, `Status changed to ${TICKET_STATUS_LABEL[nextStatus]}.`)}>
                Save status
              </button>
            </div>
          )}
        </section>
      )}

      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert" className="error">{error}</p>}
    </div>
  );
}
