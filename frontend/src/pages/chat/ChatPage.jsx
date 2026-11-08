import { useCallback, useEffect, useRef, useState } from "react";
import Shell from "../../components/Shell";
import ForwardDialog from "../../components/ForwardDialog";
import { ApiError } from "../../lib/api";
import { authedRequest } from "../../lib/session";
import { formatCitation, formatDate } from "../../lib/format";

const LINKS = [{ to: "/student/tickets", label: "My tickets" }];

export default function ChatPage() {
  const [conversations, setConversations] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [forwardFor, setForwardFor] = useState(null);
  const [notice, setNotice] = useState(null);
  const bottom = useRef(null);

  const loadConversations = useCallback(() => {
    authedRequest("/chat/conversations?limit=50").then((page) => setConversations(page.items)).catch(() => {});
  }, []);

  const loadMessages = useCallback(async (id) => {
    if (!id) return setMessages([]);
    try {
      const page = await authedRequest(`/chat/conversations/${id}/messages?limit=100`);
      setMessages(page.items);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => { loadConversations(); }, [loadConversations]);
  useEffect(() => { loadMessages(activeId); }, [activeId, loadMessages]);
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [messages]);

  async function handleAsk(event) {
    event.preventDefault();
    const text = question.trim();
    if (!text) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await authedRequest("/chat/ask", {
        method: "POST",
        body: { question: text, conversation_id: activeId },
      });
      setQuestion("");
      if (!activeId) {
        setActiveId(result.conversation_id);
        loadConversations();
      }
      await loadMessages(result.conversation_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The question could not be answered right now.");
    } finally {
      setBusy(false);
    }
  }

  function startNew() {
    setActiveId(null);
    setMessages([]);
    setNotice(null);
  }

  function forwardedOk(ticket) {
    setForwardFor(null);
    setNotice(`Sent to faculty as ticket ${ticket.ticket_number}. You can track it under My tickets.`);
    loadMessages(activeId);
  }

  return (
    <Shell title="Ask UniBuddy" links={LINKS}>
      <p className="hint">
        Answers come only from official documents that have been published on UniBuddy. Each answer shows its source.
        If the documents do not answer your question, you can send it to faculty.
      </p>
      <div className="chat-layout">
        <aside className="card">
          <button type="button" onClick={startNew}>New question</button>
          <ul className="plain-list">
            {conversations.map((c) => (
              <li key={c.id}>
                <button type="button" className="link-button" onClick={() => setActiveId(c.id)} aria-current={c.id === activeId}>
                  {c.title || "Untitled"}
                </button>
                <span className="hint">{formatDate(c.created_at)}</span>
              </li>
            ))}
          </ul>
        </aside>
        <section className="card chat-panel">
          <div className="messages" aria-live="polite">
            {messages.length === 0 && <p className="hint">Ask a question about your campus.</p>}
            {messages.map((m, index) => (
              <Message
                key={m.id}
                message={m}
                onForward={() => {
                  const prior = messages.slice(0, index).reverse().find((x) => x.role === "user");
                  setForwardFor(prior ?? null);
                }}
              />
            ))}
            <div ref={bottom} />
          </div>
          {notice && <p role="status">{notice}</p>}
          {error && <p role="alert" className="error">{error}</p>}
          <form onSubmit={handleAsk} className="ask-form">
            <input
              aria-label="Your question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              maxLength={1000}
              placeholder="Ask about fees, exams, timetables…"
              required
            />
            <button type="submit" disabled={busy}>{busy ? "Checking documents…" : "Ask"}</button>
          </form>
        </section>
      </div>
      {forwardFor && (
        <ForwardDialog
          messageId={forwardFor.id}
          question={forwardFor.content}
          onClose={() => setForwardFor(null)}
          onForwarded={forwardedOk}
        />
      )}
    </Shell>
  );
}

function Message({ message, onForward }) {
  const isUser = message.role === "user";
  const hasSources = message.citations?.length > 0;
  return (
    <div className={`bubble ${isUser ? "bubble-user" : "bubble-ai"}`}>
      <p>{message.content}</p>
      {!isUser && hasSources && (
        <ul className="citations" aria-label="Sources">
          {message.citations.map((c, i) => <li key={`${c.document_id}-${c.page}-${i}`}>Source: {formatCitation(c)}</li>)}
        </ul>
      )}
      {!isUser && !hasSources && (
        <button type="button" className="secondary" onClick={onForward}>Send this question to faculty</button>
      )}
    </div>
  );
}
