import { useEffect, useState } from "react";
import {
  getCompare,
  getPlayer,
  type Player,
  type PlayerDetail,
  type PlayerMetrics,
  type WaiverPlayer,
} from "../api";

// Metrics compared head-to-head (all "higher is better").
const ROWS: { key: keyof PlayerMetrics; label: string }[] = [
  { key: "opportunity_score", label: "Recent Role" },
  { key: "snap_pct", label: "Snap %" },
  { key: "target_share", label: "Target Share" },
  { key: "volume_pg", label: "Volume/gm" },
  { key: "ppr_pg", label: "PPR/gm" },
];

function fmt(key: keyof PlayerMetrics, v: number | null): string {
  if (v == null) return "—";
  if (key === "snap_pct" || key === "target_share") return `${Math.round(v * 100)}%`;
  if (key === "opportunity_score") return v.toFixed(2);
  return String(v);
}

interface Props {
  leagueId: string;
  rosterPlayers: Player[];
  waiverPlayers: WaiverPlayer[];
  onClose: () => void;
}

export default function ComparePlayers({
  leagueId,
  rosterPlayers,
  waiverPlayers,
  onClose,
}: Props) {
  const [aId, setAId] = useState("");
  const [bId, setBId] = useState("");
  const [a, setA] = useState<PlayerDetail | null>(null);
  const [b, setB] = useState<PlayerDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [verdict, setVerdict] = useState<string | null>(null);
  const [verdictLoading, setVerdictLoading] = useState(false);

  useEffect(() => {
    setVerdict(null);
    if (!aId || !bId) {
      setA(null);
      setB(null);
      return;
    }
    setLoading(true);
    setError(null);
    Promise.all([getPlayer(aId), getPlayer(bId)])
      .then(([pa, pb]) => {
        setA(pa);
        setB(pb);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [aId, bId]);

  function runVerdict() {
    setVerdictLoading(true);
    setError(null);
    getCompare(leagueId, aId, bId)
      .then((r) => setVerdict(r.text))
      .catch((e: Error) => setError(e.message))
      .finally(() => setVerdictLoading(false));
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="Close">
          ×
        </button>

        <h2>Compare Players</h2>
        <div className="compare-pickers">
          <select value={aId} onChange={(e) => setAId(e.target.value)}>
            <option value="">Your player…</option>
            {rosterPlayers
              .filter((p) => p.gsis_id)
              .map((p) => (
                <option key={p.gsis_id} value={p.gsis_id as string}>
                  {p.position ?? "—"} · {p.name}
                </option>
              ))}
          </select>
          <span className="compare-vs">vs</span>
          <select value={bId} onChange={(e) => setBId(e.target.value)}>
            <option value="">Waiver player…</option>
            {waiverPlayers.map((p) => (
              <option key={p.gsis_id} value={p.gsis_id}>
                {p.position ?? "—"} · {p.name}
              </option>
            ))}
          </select>
        </div>

        {error && <p className="error">{error}</p>}
        {loading && <p>Loading…</p>}

        {a && b && (
          <>
            <table className="compare-table">
              <thead>
                <tr>
                  <th></th>
                  <th>{a.name}</th>
                  <th>{b.name}</th>
                </tr>
              </thead>
              <tbody>
                {ROWS.map(({ key, label }) => {
                  const av = a.metrics[key];
                  const bv = b.metrics[key];
                  const aWin = av != null && bv != null && av > bv;
                  const bWin = av != null && bv != null && bv > av;
                  return (
                    <tr key={key}>
                      <td className="metric-name">{label}</td>
                      <td className={`num ${aWin ? "win" : ""}`}>{fmt(key, av)}</td>
                      <td className={`num ${bWin ? "win" : ""}`}>{fmt(key, bv)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {!verdict && !verdictLoading && (
              <button className="waiver-btn" onClick={runVerdict}>
                Get verdict
              </button>
            )}
            {verdictLoading && <p>Weighing them up…</p>}
            {verdict && (
              <div className="outlook-text">
                {verdict
                  .split("\n")
                  .filter((l) => l.trim())
                  .map((l, i) => (
                    <p key={i}>{l}</p>
                  ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
