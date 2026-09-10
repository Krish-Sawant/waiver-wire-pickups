import { useEffect, useState } from "react";
import { getLeagues, type League } from "./api";
import LeagueList from "./components/LeagueList";
import RosterDashboard from "./components/RosterDashboard";

export default function App() {
  const [leagues, setLeagues] = useState<League[]>([]);
  const [selected, setSelected] = useState<League | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getLeagues()
      .then(setLeagues)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <header className="topbar">
        <span className="topbar-title">Fantasy Football Waiver Helper</span>
      </header>

      <main className="app">
        {error && <p className="error">{error}</p>}
        {selected ? (
          <RosterDashboard league={selected} onBack={() => setSelected(null)} />
        ) : loading ? (
          <p>Loading leagues…</p>
        ) : (
          <LeagueList leagues={leagues} onSelect={setSelected} />
        )}
      </main>
    </>
  );
}
