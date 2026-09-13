import { useState, type FormEvent } from "react";
import { linkSleeper } from "../api";

export default function LinkSleeper({
  current,
  onLinked,
  onCancel,
}: {
  current?: string | null;
  onLinked: (sleeperUsername: string) => void;
  onCancel?: () => void;
}) {
  const [username, setUsername] = useState(current ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const relinking = !!current;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await linkSleeper(username.trim());
      onLinked(me.sleeper_username ?? username.trim());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="login-card" onSubmit={submit}>
      <h2>{relinking ? "Change Sleeper account" : "Link your Sleeper account"}</h2>
      <p className="login-hint">
        {relinking ? (
          <>
            Currently linked to <strong>@{current}</strong>. Enter a different
            Sleeper username to switch.
          </>
        ) : (
          <>
            Enter your Sleeper username so we can pull your leagues, rosters, and
            matchups. This is the name you use to log in to Sleeper.
          </>
        )}
      </p>
      <input
        type="text"
        placeholder="Sleeper username"
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        autoFocus
      />
      {error && <p className="error">{error}</p>}
      <button
        className="waiver-btn"
        type="submit"
        disabled={busy || !username.trim() || username.trim() === current}
      >
        {busy ? "Linking…" : relinking ? "Switch account" : "Link account"}
      </button>
      {onCancel && (
        <button type="button" className="login-switch" onClick={onCancel}>
          Cancel
        </button>
      )}
    </form>
  );
}
