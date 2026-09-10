// Typed client for the FastAPI backend (waiverwire.api), which wraps Sleeper +
// nflverse. The backend resolves player names and reads the username from .env,
// so the browser never talks to Sleeper directly.

const BASE = "http://localhost:8000/api";

export interface League {
  league_id: string;
  name: string;
  season: string;
  status: string;
  total_rosters: number;
  sport: string;
  avatar: string | null;
  scoring: number | null;
}

export interface Player {
  player_id: string;
  gsis_id: string | null;
  name: string;
  position: string | null;
  team: string | null;
}

export interface Roster {
  starters: Player[];
  bench: Player[];
  wins: number | null;
  losses: number | null;
  ties: number | null;
}

export interface WaiverPlayer {
  gsis_id: string;
  name: string;
  position: string | null;
  ppr_pg: number | null;
}

export interface WaiverBoard {
  season: number;
  week: number;
  players: WaiverPlayer[];
}

export interface PlayerMetrics {
  opportunity_score: number | null;
  snap_pct: number | null;
  target_share: number | null;
  volume_pg: number | null;
  ppr_pg: number | null;
  gap_pg: number | null;
  games: number | null;
}

export interface GameLogRow {
  week: number;
  opponent: string | null;
  fantasy_points_ppr: number | null;
  completions: number | null;
  attempts: number | null;
  passing_yards: number | null;
  passing_tds: number | null;
  passing_interceptions: number | null;
  carries: number | null;
  rushing_yards: number | null;
  rushing_tds: number | null;
  targets: number | null;
  receptions: number | null;
  receiving_yards: number | null;
  receiving_tds: number | null;
}

export interface PlayerDetail {
  gsis_id: string;
  name: string;
  position: string | null;
  team: string | null;
  headshot_url: string | null;
  season: number;
  metrics: PlayerMetrics;
  game_log: GameLogRow[];
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export function getLeagues(): Promise<League[]> {
  return getJSON<League[]>("/leagues");
}

export function getRoster(leagueId: string): Promise<Roster> {
  return getJSON<Roster>(`/leagues/${leagueId}/roster`);
}

export function getWaiver(leagueId: string): Promise<WaiverBoard> {
  return getJSON<WaiverBoard>(`/leagues/${leagueId}/waiver`);
}

export function getPlayer(gsisId: string): Promise<PlayerDetail> {
  return getJSON<PlayerDetail>(`/players/${gsisId}`);
}

export interface Outlook {
  text: string;
}

export function getOutlook(leagueId: string, gsisId: string): Promise<Outlook> {
  return getJSON<Outlook>(`/leagues/${leagueId}/outlook/${gsisId}`);
}
