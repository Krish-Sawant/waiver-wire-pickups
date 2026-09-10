import { useEffect, useState, type ReactNode } from "react";
import { getOutlook, getPlayer, type GameLogRow, type PlayerDetail } from "../api";

interface Col {
  key: keyof GameLogRow;
  label: string;
}

// Game-log columns depend on the player's position.
function columnsFor(position: string | null): Col[] {
  const lead: Col[] = [
    { key: "week", label: "Wk" },
    { key: "opponent", label: "Opp" },
  ];
  const fp: Col = { key: "fantasy_points_ppr", label: "FP" };

  if (position === "QB") {
    return [
      ...lead,
      { key: "completions", label: "Cmp" },
      { key: "attempts", label: "Att" },
      { key: "passing_yards", label: "Pass Yd" },
      { key: "passing_tds", label: "Pass TD" },
      { key: "passing_interceptions", label: "INT" },
      { key: "rushing_yards", label: "Rush Yd" },
      { key: "rushing_tds", label: "Rush TD" },
      fp,
    ];
  }
  if (position === "RB") {
    return [
      ...lead,
      { key: "carries", label: "Car" },
      { key: "rushing_yards", label: "Rush Yd" },
      { key: "rushing_tds", label: "Rush TD" },
      { key: "targets", label: "Tgt" },
      { key: "receptions", label: "Rec" },
      { key: "receiving_yards", label: "Rec Yd" },
      { key: "receiving_tds", label: "Rec TD" },
      fp,
    ];
  }
  // WR / TE (and anything else) — receiving-focused
  return [
    ...lead,
    { key: "targets", label: "Tgt" },
    { key: "receptions", label: "Rec" },
    { key: "receiving_yards", label: "Rec Yd" },
    { key: "receiving_tds", label: "Rec TD" },
    fp,
  ];
}

function pct(v: number | null): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

function cell(v: number | string | null): string {
  return v == null ? "—" : String(v);
}

function Metric({
  label,
  value,
  highlight,
}: {
  label: string;
  value: ReactNode;
  highlight?: boolean;
}) {
  return (
    <div className={`metric ${highlight ? "metric-hi" : ""}`}>
      <span className="metric-val">{value}</span>
      <span className="metric-label">{label}</span>
    </div>
  );
}

interface Props {
  gsisId: string;
  leagueId: string;
  onClose: () => void;
}

export default function PlayerCard({ gsisId, leagueId, onClose }: Props) {
  const [detail, setDetail] = useState<PlayerDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [outlook, setOutlook] = useState<string | null>(null);
  const [outlookLoading, setOutlookLoading] = useState(false);
  const [outlookError, setOutlookError] = useState<string | null>(null);
  const [season, setSeason] = useState<number | null>(null);

  useEffect(() => {
    setDetail(null);
    setError(null);
    setOutlook(null);
    setOutlookError(null);
    setSeason(null);
    getPlayer(gsisId)
      .then(setDetail)
      .catch((e: Error) => setError(e.message));
  }, [gsisId]);

  function runOutlook() {
    setOutlookLoading(true);
    setOutlookError(null);
    getOutlook(leagueId, gsisId)
      .then((r) => setOutlook(r.text))
      .catch((e: Error) => setOutlookError(e.message))
      .finally(() => setOutlookLoading(false));
  }

  const cols = detail ? columnsFor(detail.position) : [];

  // Seasons present in the log, newest first; default the tab to the newest.
  const seasons = detail
    ? [...new Set(detail.game_log.map((r) => r.season))].sort((a, b) => b - a)
    : [];
  const activeSeason = season ?? seasons[0] ?? null;
  const seasonRows =
    detail && activeSeason != null
      ? detail.game_log
          .filter((r) => r.season === activeSeason)
          .sort((a, b) => a.week - b.week)
      : [];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="Close">
          ×
        </button>

        {error && <p className="error">{error}</p>}
        {!detail && !error && <p>Loading…</p>}

        {detail && (
          <>
            <div className="player-head">
              {detail.headshot_url ? (
                <img
                  className="headshot"
                  src={detail.headshot_url}
                  alt={detail.name}
                />
              ) : (
                <div className="headshot headshot-placeholder" />
              )}
              <div>
                <h2>{detail.name}</h2>
                <p className="player-sub">
                  {detail.position ?? "—"} · {detail.team ?? "FA"}
                </p>
              </div>
            </div>

            <h3>
              Pickup metrics{" "}
              <span className="muted">
                (rolling {detail.metrics.games ?? 0}-game window)
              </span>
            </h3>
            <div className="metric-grid">
              <Metric
                label="Recent Role"
                value={detail.metrics.opportunity_score?.toFixed(2) ?? "—"}
                highlight
              />
              <Metric label="Snap %" value={pct(detail.metrics.snap_pct)} />
              <Metric label="Target Share" value={pct(detail.metrics.target_share)} />
              <Metric label="Volume/gm" value={detail.metrics.volume_pg ?? "—"} />
              <Metric label="PPR/gm" value={detail.metrics.ppr_pg ?? "—"} />
              <Metric label="Pts vs Exp" value={detail.metrics.gap_pg ?? "—"} />
            </div>

            <div className="gamelog-head">
              <h3>Game log</h3>
              <div className="season-tabs">
                {seasons.map((s) => (
                  <button
                    key={s}
                    className={`season-tab ${s === activeSeason ? "active" : ""}`}
                    onClick={() => setSeason(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
            <div className="log-scroll">
              {seasonRows.length === 0 ? (
                <p className="empty">No games this season.</p>
              ) : (
                <table className="gamelog">
                  <thead>
                    <tr>
                      {cols.map((c) => (
                        <th
                          key={c.key}
                          className={c.key === "opponent" ? "" : "num"}
                        >
                          {c.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {seasonRows.map((row) => (
                      <tr key={row.week}>
                        {cols.map((c) => (
                          <td
                            key={c.key}
                            className={c.key === "opponent" ? "" : "num"}
                          >
                            {cell(row[c.key])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <h3>Fantasy Outlook</h3>
            {!outlook && !outlookLoading && (
              <button className="waiver-btn" onClick={runOutlook}>
                Analyze vs. my roster
              </button>
            )}
            {outlookLoading && <p>Analyzing your roster…</p>}
            {outlookError && <p className="error">{outlookError}</p>}
            {outlook && (
              <div className="outlook-text">
                {outlook
                  .split("\n")
                  .filter((line) => line.trim())
                  .map((line, i) => (
                    <p key={i}>{line}</p>
                  ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
