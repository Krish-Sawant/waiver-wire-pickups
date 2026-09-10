import { useEffect, useState } from "react";
import {
  getRoster,
  getWaiver,
  type League,
  type Player,
  type Roster,
  type WaiverBoard,
} from "../api";
import PlayerCard from "./PlayerCard";

function RosterTable({
  players,
  onSelect,
}: {
  players: Player[];
  onSelect: (gsisId: string) => void;
}) {
  if (!players.length) return <p className="empty">None</p>;
  return (
    <table className="roster">
      <tbody>
        {players.map((p) => (
          <tr
            key={p.player_id}
            className={p.gsis_id ? "waiver-row" : ""}
            onClick={p.gsis_id ? () => onSelect(p.gsis_id!) : undefined}
          >
            <td className="pos">{p.position ?? "—"}</td>
            <td>{p.name}</td>
            <td className="team">{p.team ?? "FA"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function WaiverBoardView({
  board,
  leagueId,
}: {
  board: WaiverBoard;
  leagueId: string;
}) {
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <>
      <p className="record">
        Best available · {board.season} season, through week {board.week} · click a
        player for full details
      </p>
      <table className="roster waiver-table">
        <thead>
          <tr>
            <th className="rank">#</th>
            <th className="pos">Pos</th>
            <th>Player</th>
            <th className="num">Fantasy Pts/gm</th>
          </tr>
        </thead>
        <tbody>
          {board.players.map((p, i) => (
            <tr
              key={p.gsis_id}
              className="waiver-row"
              onClick={() => setSelected(p.gsis_id)}
            >
              <td className="rank">{i + 1}</td>
              <td className="pos">{p.position ?? "—"}</td>
              <td>{p.name}</td>
              <td className="num">{p.ppr_pg ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {selected && (
        <PlayerCard
          gsisId={selected}
          leagueId={leagueId}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}

interface Props {
  league: League;
  onBack: () => void;
}

export default function RosterDashboard({ league, onBack }: Props) {
  const [roster, setRoster] = useState<Roster | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"roster" | "waiver">("roster");

  const [board, setBoard] = useState<WaiverBoard | null>(null);
  const [waiverError, setWaiverError] = useState<string | null>(null);
  const [waiverLoading, setWaiverLoading] = useState(false);
  const [rosterPlayer, setRosterPlayer] = useState<string | null>(null);

  // Load the roster (and reset waiver state) whenever the league changes.
  useEffect(() => {
    setRoster(null);
    setError(null);
    setView("roster");
    setBoard(null);
    setWaiverError(null);
    setRosterPlayer(null);
    getRoster(league.league_id)
      .then(setRoster)
      .catch((e: Error) => setError(e.message));
  }, [league.league_id]);

  // Fetch the waiver board lazily, the first time the user opens that view.
  useEffect(() => {
    if (view !== "waiver" || board || waiverLoading) return;
    setWaiverLoading(true);
    setWaiverError(null);
    getWaiver(league.league_id)
      .then(setBoard)
      .catch((e: Error) => setWaiverError(e.message))
      .finally(() => setWaiverLoading(false));
  }, [view, league.league_id, board, waiverLoading]);

  return (
    <div>
      <button className="back" onClick={onBack}>
        ← Leagues
      </button>

      <div className="roster-header">
        <h2>{league.name}</h2>
        {view === "roster" ? (
          <button className="waiver-btn" onClick={() => setView("waiver")}>
            View Waiver Wire
          </button>
        ) : (
          <button className="waiver-btn" onClick={() => setView("roster")}>
            ← Back to Roster
          </button>
        )}
      </div>

      {view === "waiver" ? (
        <>
          {waiverLoading && (
            <p>Loading waiver rankings… first load pulls season data, ~a few seconds.</p>
          )}
          {waiverError && <p className="error">{waiverError}</p>}
          {board && (
            <WaiverBoardView board={board} leagueId={league.league_id} />
          )}
        </>
      ) : (
        <>
          {error && <p className="error">{error}</p>}
          {!roster && !error && <p>Loading roster…</p>}
          {roster && (
            <>
              {roster.wins != null && (
                <p className="record">
                  Record: {roster.wins}–{roster.losses}
                  {roster.ties ? `–${roster.ties}` : ""}
                </p>
              )}
              <div className="roster-columns">
                <section>
                  <h3>Starters</h3>
                  <RosterTable
                    players={roster.starters}
                    onSelect={setRosterPlayer}
                  />
                </section>
                <section>
                  <h3>Bench</h3>
                  <RosterTable players={roster.bench} onSelect={setRosterPlayer} />
                </section>
              </div>
              {rosterPlayer && (
                <PlayerCard
                  gsisId={rosterPlayer}
                  leagueId={league.league_id}
                  onClose={() => setRosterPlayer(null)}
                />
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
