import { useEffect, useState } from "react";
import { ApiError } from "../lib/api";
import { authedRequest } from "../lib/session";

export default function ForwardDialog({ messageId, question, onClose, onForwarded }) {
  const [departments, setDepartments] = useState([]);
  const [departmentId, setDepartmentId] = useState("");
  const [priority, setPriority] = useState("medium");
  const [description, setDescription] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    authedRequest("/departments").then(setDepartments).catch((err) => setError(err.message));
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!departmentId) return setError("Choose the department that should answer.");
    setBusy(true);
    setError(null);
    try {
      const ticket = await authedRequest(`/chat/messages/${messageId}/forward`, {
        method: "POST",
        body: { department_id: departmentId, priority, description: description.trim() || null },
      });
      onForwarded(ticket);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The question could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="dialog-backdrop" role="presentation">
      <section className="card dialog" role="dialog" aria-modal="true" aria-labelledby="forward-title">
        <h2 id="forward-title">Send to faculty</h2>
        <p className="hint">“{question}”</p>
        <form onSubmit={handleSubmit} className="stack">
          <label>
            Department
            <select value={departmentId} onChange={(e) => setDepartmentId(e.target.value)} required>
              <option value="">Choose a department</option>
              {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </label>
          <label>
            Priority
            <select value={priority} onChange={(e) => setPriority(e.target.value)}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>
          <label>
            Anything faculty should know (optional)
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} rows={3} />
          </label>
          {error && <p role="alert" className="error">{error}</p>}
          <div className="row">
            <button type="submit" disabled={busy}>{busy ? "Sending…" : "Send to faculty"}</button>
            <button type="button" className="secondary" onClick={onClose}>Cancel</button>
          </div>
        </form>
      </section>
    </div>
  );
}
