// Typed client for the FastAPI backend (waiverwire.api), which wraps Sleeper +
// nflverse. The backend resolves player names and reads the username from .env,
// so the browser never talks to Sleeper directly.

import { clearToken, getToken, setToken } from "./auth";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

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
  games: number | null;
  injury_status: string | null;
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
  season: number;
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
  injury_status: string | null;
  depth: string | null;
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function handle<T>(res: Response): Promise<T> {
  if (res.status === 401) {
    // Session missing/expired — drop the token and bounce to the login gate.
    clearToken();
    window.location.reload();
    throw new Error("Session expired");
  }
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

function getJSON<T>(path: string): Promise<T> {
  return fetch(`${BASE}${path}`, { headers: authHeaders() }).then((r) => handle<T>(r));
}

function postJSON<T>(path: string, body: unknown): Promise<T> {
  return fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(body),
  }).then((r) => handle<T>(r));
}

// Login/signup use their own fetch so a 4xx (wrong password, email taken)
// surfaces to the form instead of triggering the reload-to-login in handle().
async function authRequest(path: string, email: string, password: string): Promise<void> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    let detail = "Request failed";
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  const { token } = (await res.json()) as { token: string };
  setToken(token);
}

export function login(email: string, password: string): Promise<void> {
  return authRequest("/login", email, password);
}

export function signup(email: string, password: string): Promise<void> {
  return authRequest("/signup", email, password);
}

export interface Me {
  email: string;
  sleeper_username: string | null;
}

export function getMe(): Promise<Me> {
  return getJSON<Me>("/me");
}

export function linkSleeper(sleeperUsername: string): Promise<Me> {
  return postJSON<Me>("/me/sleeper", { sleeper_username: sleeperUsername });
}

export function getLeagues(): Promise<League[]> {
  return getJSON<League[]>("/leagues");
}

export function getRoster(leagueId: string): Promise<Roster> {
  return getJSON<Roster>(`/leagues/${leagueId}/roster`);
}

export function getWaiver(leagueId: string, top = 200): Promise<WaiverBoard> {
  return getJSON<WaiverBoard>(`/leagues/${leagueId}/waiver?top=${top}`);
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

export interface ChatTurn {
  role: "user" | "assistant";
  text: string;
}

export function postChat(
  leagueId: string,
  messages: ChatTurn[]
): Promise<{ text: string }> {
  return postJSON<{ text: string }>(`/leagues/${leagueId}/chat`, { messages });
}

export function getCompare(
  leagueId: string,
  gsisA: string,
  gsisB: string
): Promise<{ text: string }> {
  return getJSON<{ text: string }>(`/leagues/${leagueId}/compare/${gsisA}/${gsisB}`);
}
