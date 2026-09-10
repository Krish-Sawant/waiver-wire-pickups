import { useEffect, useRef, useState, type FormEvent } from "react";
import { postChat, type ChatTurn } from "../api";

type Message = ChatTurn & { hidden?: boolean };

// Hidden first turn that seeds the auto-generated report on open.
const STARTUP =
  "Give me my waiver report: the top players I should pick up across all " +
  "positions, and for the best targets, who on my roster I should consider " +
  "dropping to add them. Be concise.";

export default function WaiverChat({ leagueId }: { leagueId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  async function send(history: Message[]) {
    setLoading(true);
    setError(null);
    try {
      const payload: ChatTurn[] = history.map((m) => ({ role: m.role, text: m.text }));
      const r = await postChat(leagueId, payload);
      setMessages([...history, { role: "assistant", text: r.text }]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  // On open (and league change), fire the hidden startup prompt for the report.
  useEffect(() => {
    const start: Message[] = [{ role: "user", text: STARTUP, hidden: true }];
    setMessages(start);
    setError(null);
    send(start);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leagueId]);

  // Keep the latest message in view.
  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight });
  }, [messages, loading]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    const next: Message[] = [...messages, { role: "user", text }];
    setMessages(next);
    setInput("");
    send(next);
  }

  const visible = messages.filter((m) => !m.hidden);

  return (
    <aside className="chat-panel">
      <div className="chat-header">Waiver Assistant</div>
      <div className="chat-body" ref={bodyRef}>
        {visible.map((m, i) => (
          <div key={i} className={`chat-msg chat-${m.role}`}>
            {m.text}
          </div>
        ))}
        {loading && (
          <div className="chat-msg chat-assistant chat-loading">Thinking…</div>
        )}
        {error && <div className="chat-msg chat-error">{error}</div>}
      </div>
      <form className="chat-input" onSubmit={onSubmit}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a follow-up…"
          disabled={loading}
        />
        <button type="submit" disabled={loading || !input.trim()}>
          Send
        </button>
      </form>
    </aside>
  );
}
