import type { League } from "../api";

function scoringLabel(rec: number | null): string {
  if (rec === 1) return "PPR";
  if (rec === 0.5) return "Half-PPR";
  return "Standard";
}

interface Props {
  leagues: League[];
  onSelect: (league: League) => void;
}

export default function LeagueList({ leagues, onSelect }: Props) {
  if (!leagues.length) return <p>No leagues found.</p>;

  return (
    <div className="league-grid">
      {leagues.map((lg) => (
        <button
          key={lg.league_id}
          className="league-card"
          onClick={() => onSelect(lg)}
        >
          <span className="league-card-name">{lg.name}</span>
          <span className="league-card-meta">
            {lg.season} · {lg.total_rosters}-team · {scoringLabel(lg.scoring)}
          </span>
          <span className="league-card-status">{lg.status.replace("_", " ")}</span>
        </button>
      ))}
    </div>
  );
}
