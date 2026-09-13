import { useEffect, useState } from "react";
import {
  getRoster,
  getWaiver,
  type League,
  type Player,
  type Roster,
  type WaiverBoard,
} from "../api";
import { useShortlist } from "../useShortlist";
import ComparePlayers from "./ComparePlayers";
import PlayerCard from "./PlayerCard";
import WaiverChat from "./WaiverChat";

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
  rosterPlayers,
}: {
  board: WaiverBoard;
  leagueId: string;
  rosterPlayers: Player[];
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [comparing, setComparing] = useState(false);
  const [search, setSearch] = useState("");
  const [posFilter, setPosFilter] = useState("");
  const [mode, setMode] = useState<"board" | "shortlist">("board");
  const { items: shortlist, has, toggle } = useShortlist(leagueId);

  const query = search.trim().toLowerCase();
  const filtered = board.players.filter(
    (p) =>
      (posFilter === "" || p.position === posFilter) &&
      (query === "" || p.name.toLowerCase().includes(query))
  );

  const POSITIONS = ["QB", "RB", "WR", "TE"];
  const rows = mode === "shortlist" ? shortlist : filtered;
  const injuryOf = (id: string) =>
    board.players.find((p) => p.gsis_id === id)?.injury_status ?? null;

  return (
    <>
      <div className="waiver-layout">
        <div className="waiver-main">
          <div className="waiver-toolbar">
            <p className="record">
              {mode === "board"
                ? `Best available · ${board.season} season, through week ${board.week} · click a player for full details`
                : `Your shortlist · ${shortlist.length} player${
                    shortlist.length === 1 ? "" : "s"
                  }`}
            </p>
            <div className="toolbar-actions">
              <button
                className="waiver-btn"
                onClick={() => setMode(mode === "board" ? "shortlist" : "board")}
              >
                {mode === "board"
                  ? `★ Shortlist (${shortlist.length})`
                  : "← Back to Board"}
              </button>
              <button className="waiver-btn" onClick={() => setComparing(true)}>
                Compare Players
              </button>
            </div>
          </div>

          {mode === "board" && (
            <div className="filter-bar">
              <input
                className="player-search"
                type="text"
                placeholder="Search players…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <div className="pos-filter">
                <button
                  className={`pos-tab ${posFilter === "" ? "active" : ""}`}
                  onClick={() => setPosFilter("")}
                >
                  All
                </button>
                {POSITIONS.map((pos) => (
                  <button
                    key={pos}
                    className={`pos-tab ${posFilter === pos ? "active" : ""}`}
                    onClick={() => setPosFilter(pos)}
                  >
                    {pos}
                  </button>
                ))}
              </div>
            </div>
          )}

          <table className="roster waiver-table">
            <thead>
              <tr>
                <th className="rank">#</th>
                <th className="pos">Pos</th>
                <th>Player</th>
                <th className="num">Fantasy Pts/gm</th>
                <th className="star-col"></th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td colSpan={5} className="empty">
                    {mode === "shortlist"
                      ? "No shortlisted players yet — tap ☆ on the board to add one."
                      : "No players match."}
                  </td>
                </tr>
              )}
              {rows.map((p, i) => {
                const inj = injuryOf(p.gsis_id);
                return (
                  <tr
                    key={p.gsis_id}
                    className="waiver-row"
                    onClick={() => setSelected(p.gsis_id)}
                  >
                    <td className="rank">{i + 1}</td>
                    <td className="pos">{p.position ?? "—"}</td>
                    <td>
                      {p.name}
                      {inj && (
                        <span
                          className={`inj-badge ${
                            inj === "Out" || inj === "Inactive" ? "inj-out" : "inj-q"
                          }`}
                        >
                          {inj === "Out"
                            ? "OUT"
                            : inj === "Doubtful"
                              ? "D"
                              : inj === "Inactive"
                                ? "INA"
                                : "Q"}
                        </span>
                      )}
                    </td>
                    <td className="num">{p.ppr_pg ?? "—"}</td>
                    <td
                      className="star-cell"
                      title={
                        has(p.gsis_id)
                          ? "Remove from shortlist"
                          : "Add to shortlist"
                      }
                      onClick={(e) => {
                        e.stopPropagation();
                        toggle({
                          gsis_id: p.gsis_id,
                          name: p.name,
                          position: p.position,
                          ppr_pg: p.ppr_pg,
                        });
                      }}
                    >
                      {has(p.gsis_id) ? "★" : "☆"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <WaiverChat leagueId={leagueId} />
      </div>

      {selected && (
        <PlayerCard
          gsisId={selected}
          leagueId={leagueId}
          onClose={() => setSelected(null)}
        />
      )}

      {comparing && (
        <ComparePlayers
          leagueId={leagueId}
          rosterPlayers={rosterPlayers}
          waiverPlayers={board.players}
          onClose={() => setComparing(false)}
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
            <WaiverBoardView
              board={board}
              leagueId={league.league_id}
              rosterPlayers={roster ? [...roster.starters, ...roster.bench] : []}
            />
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
