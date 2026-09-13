import { useEffect, useState } from "react";
import { getLeagues, getMe, type League } from "./api";
import { clearToken, getToken } from "./auth";
import LeagueList from "./components/LeagueList";
import LinkSleeper from "./components/LinkSleeper";
import Login from "./components/Login";
import RosterDashboard from "./components/RosterDashboard";

export default function App() {
  const [authed, setAuthed] = useState<boolean>(!!getToken());
  const [checked, setChecked] = useState(false); // has getMe() resolved yet?
  const [sleeperName, setSleeperName] = useState<string | null>(null);
  const [relinking, setRelinking] = useState(false); // user wants to change it
  const [leagues, setLeagues] = useState<League[]>([]);
  const [selected, setSelected] = useState<League | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Once past the login gate, find out which Sleeper account (if any) is linked.
  useEffect(() => {
    if (!authed) return;
    setChecked(false);
    getMe()
      .then((me) => setSleeperName(me.sleeper_username))
      .catch((e: Error) => setError(e.message))
      .finally(() => setChecked(true));
  }, [authed]);

  // Reload leagues whenever the linked account changes (and there is one).
  useEffect(() => {
    if (!authed || !sleeperName) return;
    setSelected(null);
    setLoading(true);
    getLeagues()
      .then(setLeagues)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [authed, sleeperName]);

  function logout() {
    clearToken();
    setAuthed(false);
    setChecked(false);
    setSleeperName(null);
    setRelinking(false);
    setSelected(null);
    setLeagues([]);
    setError(null);
  }

  const linkView = !sleeperName || relinking;

  function renderMain() {
    if (!checked) return <p>Loading…</p>;
    if (linkView) {
      return (
        <LinkSleeper
          current={sleeperName}
          onLinked={(name) => {
            setError(null);
            setSleeperName(name);
            setRelinking(false);
          }}
          onCancel={sleeperName ? () => setRelinking(false) : undefined}
        />
      );
    }
    if (selected) {
      return <RosterDashboard league={selected} onBack={() => setSelected(null)} />;
    }
    if (loading) return <p>Loading leagues…</p>;
    return <LeagueList leagues={leagues} onSelect={setSelected} />;
  }

  return (
    <>
      <header className="topbar">
        <span className="topbar-title">Fantasy Football Waiver Helper</span>
        {authed && checked && sleeperName && !relinking && (
          <span className="topbar-account">
            <span className="sleeper-name">@{sleeperName}</span>
            <button
              className="linkbar-btn"
              onClick={() => {
                setRelinking(true);
                setSelected(null);
              }}
            >
              Change Sleeper account
            </button>
          </span>
        )}
        {authed && (
          <button className="logout-btn" onClick={logout}>
            Log out
          </button>
        )}
      </header>

      <main className="app">
        {!authed ? (
          <Login onLogin={() => setAuthed(true)} />
        ) : (
          <>
            {error && <p className="error">{error}</p>}
            {renderMain()}
          </>
        )}
      </main>
    </>
  );
}
