import { useCallback, useEffect, useState } from "react";
import Shell from "../../components/Shell";
import { useAuth } from "../../auth/AuthContext";
import { ApiError } from "../../lib/api";
import { authedRequest, authedUpload } from "../../lib/session";
import {
  DOCUMENT_PROCESSING_LABEL,
  MAX_UPLOAD_MB,
  PUBLICATION_LABEL,
  fileProblem,
  formatDate,
  isStillProcessing,
} from "../../lib/format";

export default function DocumentsPage() {
  const { profile } = useAuth();
  const isAuthority = profile?.role === "authority";
  const [documents, setDocuments] = useState(null);
  const [departments, setDepartments] = useState([]);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);

  const load = useCallback(async () => {
    try {
      const page = await authedRequest("/documents?limit=50");
      setDocuments(page.items);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    load();
    authedRequest("/departments").then(setDepartments).catch(() => {});
  }, [load]);

  // Processing runs in the background, so the list refreshes while anything is queued.
  useEffect(() => {
    if (!documents || !isStillProcessing(documents)) return undefined;
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, [documents, load]);

  async function act(path, message) {
    setError(null);
    setNotice(null);
    try {
      await authedRequest(path, { method: "POST" });
      setNotice(message);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The request could not be completed.");
    }
  }

  return (
    <Shell title="Documents">
      <UploadForm
        isAuthority={isAuthority}
        departments={departments}
        onUploaded={(doc) => {
          setNotice(`"${doc.title}" was uploaded and is being processed. It can be published once it is ready.`);
          load();
        }}
        onError={setError}
      />
      {error && <p role="alert" className="error">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <section className="card">
        <h2>Your documents</h2>
        {!documents && !error && <p role="status">Loading…</p>}
        {documents && documents.length === 0 && <p>No documents yet.</p>}
        {documents && documents.length > 0 && (
          <table>
            <thead>
              <tr><th>Title</th><th>Processing</th><th>Status</th><th>Uploaded</th><th /></tr>
            </thead>
            <tbody>
              {documents.map((doc) => (
                <tr key={doc.id}>
                  <td>
                    {doc.title}
                    <div className="hint">
                      {doc.visibility === "staff_only" ? "Staff only" : "Visible to students"} · {doc.scope === "university_wide" ? "University-wide" : "Campus"}
                    </div>
                  </td>
                  <td>
                    {DOCUMENT_PROCESSING_LABEL[doc.processing_status]}
                    {doc.page_count ? ` · ${doc.page_count} pages` : ""}
                    {doc.processing_note && <div className="hint">{doc.processing_note}</div>}
                  </td>
                  <td>{PUBLICATION_LABEL[doc.publication_status]}</td>
                  <td>{formatDate(doc.created_at)}</td>
                  <td>
                    {doc.processing_status === "ready" && doc.publication_status === "draft" && (
                      <button type="button" onClick={() => act(`/documents/${doc.id}/publish`, `"${doc.title}" is published. Students can now ask about it.`)}>
                        Publish
                      </button>
                    )}{" "}
                    {doc.publication_status !== "archived" && (
                      <button type="button" className="secondary" onClick={() => act(`/documents/${doc.id}/archive`, `"${doc.title}" is archived.`)}>
                        Archive
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </Shell>
  );
}

function UploadForm({ isAuthority, departments, onUploaded, onError }) {
  const [title, setTitle] = useState("");
  const [file, setFile] = useState(null);
  const [visibility, setVisibility] = useState("public_students");
  const [scope, setScope] = useState("campus");
  const [departmentId, setDepartmentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [localError, setLocalError] = useState(null);

  async function handleSubmit(event) {
    event.preventDefault();
    const problem = fileProblem(file);
    if (problem) return setLocalError(problem);
    if (!title.trim()) return setLocalError("Give the document a title.");
    setLocalError(null);
    setBusy(true);
    try {
      const form = new FormData();
      form.append("title", title.trim());
      form.append("file", file);
      form.append("visibility", visibility);
      form.append("scope", scope);
      if (departmentId) form.append("department_id", departmentId);
      const doc = await authedUpload("/documents", form);
      setTitle("");
      setFile(null);
      event.target.reset();
      onUploaded(doc);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : "The upload failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>Upload an official PDF</h2>
      <p className="hint">
        Only approved, official documents belong here. Up to {MAX_UPLOAD_MB} MB. Once it is ready, you publish it so students can ask about it.
        Uploaded text is processed by the AI service.
      </p>
      <form onSubmit={handleSubmit} className="stack">
        <label>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required />
        </label>
        <label>
          PDF file
          <input type="file" accept="application/pdf,.pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
        </label>
        <label>
          Who can see it
          <select value={visibility} onChange={(e) => setVisibility(e.target.value)}>
            <option value="public_students">Students and staff</option>
            <option value="staff_only">Staff only</option>
          </select>
        </label>
        <label>
          Scope
          <select value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="campus">My campus</option>
            {isAuthority && <option value="university_wide">University-wide</option>}
          </select>
        </label>
        <label>
          Department (optional)
          <select value={departmentId} onChange={(e) => setDepartmentId(e.target.value)}>
            <option value="">No department</option>
            {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </label>
        {localError && <p role="alert" className="error">{localError}</p>}
        <button type="submit" disabled={busy}>{busy ? "Uploading…" : "Upload"}</button>
      </form>
    </section>
  );
}
