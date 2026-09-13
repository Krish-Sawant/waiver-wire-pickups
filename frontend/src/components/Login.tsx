import { useState, type FormEvent } from "react";
import { login, signup } from "../api";

export default function Login({ onLogin }: { onLogin: () => void }) {
  const [mode, setMode] = useState<"login" | "signup">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isSignup = mode === "signup";

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (isSignup) {
        await signup(email, password);
      } else {
        await login(email, password);
      }
      onLogin();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function switchMode() {
    setMode(isSignup ? "login" : "signup");
    setError(null);
  }

  return (
    <form className="login-card" onSubmit={submit}>
      <h2>{isSignup ? "Create account" : "Log in"}</h2>
      <input
        type="email"
        placeholder="Email"
        autoComplete="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        autoFocus
      />
      <input
        type="password"
        placeholder="Password"
        autoComplete={isSignup ? "new-password" : "current-password"}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      {isSignup && (
        <p className="login-hint">At least 8 characters.</p>
      )}
      {error && <p className="error">{error}</p>}
      <button
        className="waiver-btn"
        type="submit"
        disabled={busy || !email || !password}
      >
        {busy
          ? isSignup
            ? "Creating account…"
            : "Signing in…"
          : isSignup
          ? "Sign up"
          : "Sign in"}
      </button>
      <button type="button" className="login-switch" onClick={switchMode}>
        {isSignup
          ? "Already have an account? Log in"
          : "Need an account? Sign up"}
      </button>
    </form>
  );
}
