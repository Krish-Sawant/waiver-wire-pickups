"""
FastAPI backend for the waiver-wire front end.

Wraps the waiverwire helpers as JSON endpoints the React app calls. Each account
links its own Sleeper username (stored per-user in the DB); league selection is
driven by the front end.

Run it with:
    uvicorn waiverwire.api:app --reload
"""

from __future__ import annotations

import math
import os
import time

import polars as pl
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types
from pydantic import BaseModel

from waiverwire.auth import create_token, require_auth
from waiverwire.users import (
    create_user,
    get_sleeper_username,
    set_sleeper_username,
    verify_user,
)

from waiverwire.nfl import (
    active_roster_ids,
    build_player_week_features,
    current_season,
    current_teams,
    depth_positions,
    get_current_injuries,
    rankable_seasons,
    sleeper_gsis_crosswalk,
)
from waiverwire.ranking import opportunity_score
from waiverwire.sleeper import get_user_id, get_user_roster, list_leagues
from waiverwire.waiver import rostered_gsis_ids

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

app = FastAPI(title="Waiver Wire API")

# The Vite dev server runs on a different port, so allow cross-origin calls.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# --- Auth (the login gate) -------------------------------------------------
class Credentials(BaseModel):
    email: str
    password: str


@app.post("/api/signup")
def signup(req: Credentials) -> dict:
    """Public endpoint. Registers a new account and logs it in."""
    email = req.email.strip().lower()
    if "@" not in email or "." not in email:
        raise HTTPException(400, "Enter a valid email address.")
    if len(req.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    try:
        create_user(email, req.password)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return {"token": create_token(email)}


@app.post("/api/login")
def login(req: Credentials) -> dict:
    """Public endpoint. Verifies the Argon2-hashed password and issues a token."""
    email = req.email.strip().lower()
    if not verify_user(email, req.password):
        raise HTTPException(401, "Invalid email or password")
    return {"token": create_token(email)}


# --- Sleeper account linking -----------------------------------------------
class SleeperLink(BaseModel):
    sleeper_username: str


def _sleeper_username(user: str) -> str:
    """The logged-in user's linked Sleeper username, or 409 if they haven't
    linked one yet. Every league/roster endpoint routes through this so each
    account only ever sees its own Sleeper data."""
    username = get_sleeper_username(user)
    if not username:
        raise HTTPException(409, "Link your Sleeper account first.")
    return username


@app.get("/api/me")
def me(user: str = Depends(require_auth)) -> dict:
    """Who's logged in and whether they've linked a Sleeper account."""
    return {"email": user, "sleeper_username": get_sleeper_username(user)}


@app.post("/api/me/sleeper")
def link_sleeper(req: SleeperLink, user: str = Depends(require_auth)) -> dict:
    """Validate a Sleeper username against Sleeper, then link it to this account."""
    username = req.sleeper_username.strip()
    if not username:
        raise HTTPException(400, "Enter your Sleeper username.")
    try:
        get_user_id(username)  # 404s at Sleeper if the username doesn't exist
    except ValueError:
        raise HTTPException(404, f"No Sleeper user named {username!r}.")
    except Exception:
        raise HTTPException(502, "Couldn't reach Sleeper. Try again in a moment.")
    set_sleeper_username(user, username)
    return {"email": user, "sleeper_username": username}


def _num(value, ndigits: int = 1):
    """Round floats and coerce NaN -> None so the payload is valid JSON."""
    if isinstance(value, float):
        return None if math.isnan(value) else round(value, ndigits)
    return value


def _player_metrics(ranked: pl.DataFrame, gid: str | None) -> dict | None:
    """Recent PPR/gm and role score for a player, or None if not in the ranking."""
    if not gid:
        return None
    row = ranked.filter(pl.col("gsis_id") == gid)
    if row.is_empty():
        return None
    m = row.to_dicts()[0]
    return {"ppr_pg": _num(m["ppr_pg"], 1), "role": _num(m["opportunity_score"], 2)}


def _injury_suffix(injuries: dict, gid: str | None) -> str:
    """An availability tag for a player if they're currently sidelined."""
    status = injuries.get(gid) if gid else None
    if not status:
        return ""
    if status == "Inactive":
        return " [INACTIVE: has not played in weeks — very risky]"
    return f" [INJURY: {status}]"


# Statuses that make a player unviable as a waiver pickup right now.
_UNAVAILABLE_STATUSES = {"Out", "Inactive"}


def _unavailable(injuries: dict) -> set[str]:
    """gsis_ids that shouldn't be recommended as pickups (Out or long-inactive)."""
    return {gid for gid, status in injuries.items() if status in _UNAVAILABLE_STATUSES}


# Deepest depth-chart rank that's still fantasy-relevant, by position.
_DEPTH_LIMIT = {"QB": 1, "RB": 2, "WR": 3, "TE": 2}


def _buried(depth: dict) -> set[str]:
    """gsis_ids buried on the depth chart beyond fantasy relevance (e.g. RB3+),
    so a backup with strong prior-season stats doesn't top the board."""
    return {
        gid
        for gid, d in depth.items()
        if d["rank"] > _DEPTH_LIMIT.get(d["pos"], 99)
    }


def _depth_label(depth: dict, gid: str | None) -> str | None:
    """A 'RB3' style label for a player's current depth-chart spot."""
    d = depth.get(gid) if gid else None
    return f"{d['pos']}{d['rank']}" if d else None


@app.get("/api/leagues")
def leagues(user: str = Depends(require_auth)) -> list[dict]:
    """Every league the logged-in user's linked Sleeper account is in."""
    return list_leagues(_sleeper_username(user))


# Sleeper's own player objects carry an (often empty) gsis_id, so we map
# Sleeper ids -> gsis ids via nflverse instead. Cache the mapping for a day.
_xw_cache: dict = {"map": None, "ts": 0.0}


def _sleeper_to_gsis() -> dict[str, str]:
    now = time.time()
    if _xw_cache["map"] is None or now - _xw_cache["ts"] > 86_400:
        xw = sleeper_gsis_crosswalk().with_columns(pl.col("sleeper_id").cast(pl.Utf8))
        _xw_cache["map"] = dict(zip(xw["sleeper_id"].to_list(), xw["gsis_id"].to_list()))
        _xw_cache["ts"] = now
    return _xw_cache["map"]


@app.get("/api/leagues/{league_id}/roster")
def roster(league_id: str, user: str = Depends(require_auth)) -> dict:
    """The user's roster in one league, with player names + gsis ids resolved."""
    result = get_user_roster(league_id, _sleeper_username(user))
    if result is None:
        raise HTTPException(404, "No roster for this user in that league")

    # Attach gsis_id so the front end can open the player detail card.
    mapping = _sleeper_to_gsis()
    for player in (*result["starters"], *result["bench"]):
        player["gsis_id"] = mapping.get(player["player_id"])

    return result


# The league-wide opportunity ranking is expensive (it downloads and joins a
# season of nflverse data), but it's identical across leagues — only the roster
# filter differs. Compute it once and cache the ranking AND the weekly feature
# frame (for per-player game logs); each request just re-filters by rostered ids.
_ranking_cache: dict = {
    "df": None,
    "feats": None,
    "injuries": None,
    "active": None,
    "teams": None,
    "depth": None,
    "season": None,
    "week": None,
    "ts": 0.0,
}


def _base_ranking() -> dict:
    now = time.time()
    if _ranking_cache["df"] is None or now - _ranking_cache["ts"] > 21_600:
        seasons = rankable_seasons()  # e.g. [2025, 2026]
        feats = build_player_week_features(seasons, include_redzone=False)
        # Report the latest (season, week) present, for the UI label. The window
        # itself spans the boundary via each player's last games played.
        reg = feats.filter(pl.col("week") <= 18)
        season = int(reg["season"].max())
        week = int(reg.filter(pl.col("season") == season)["week"].max())
        ranked = opportunity_score(seasons, features=feats)  # all games played
        injuries = get_current_injuries(seasons)  # gsis_id -> Out/Doubtful/Questionable
        cur = current_season()  # rosters, teams, and depth charts are current-season
        active = active_roster_ids(cur)  # on a current NFL roster
        teams = current_teams(cur)  # gsis_id -> current team
        depth = depth_positions(cur)  # gsis_id -> {pos, rank}
        _ranking_cache.update(
            df=ranked,
            feats=feats,
            injuries=injuries,
            active=active,
            teams=teams,
            depth=depth,
            season=season,
            week=week,
            ts=now,
        )
    return _ranking_cache


@app.get("/api/leagues/{league_id}/waiver")
def waiver(
    league_id: str, top: int = 25, _user: str = Depends(require_auth)
) -> dict:
    """Top available (unrostered) players in a league, by opportunity score.

    The list itself is intentionally lean (name, position, fantasy points) — the
    full breakdown lives in the per-player detail endpoint.
    """
    base = _base_ranking()
    ranked = base["df"]
    injuries = base["injuries"]

    taken = rostered_gsis_ids(league_id)
    if taken:
        ranked = ranked.filter(~pl.col("gsis_id").is_in(taken))

    # Keep only players actually on a current NFL roster (drops retired / cut /
    # unsigned players whose old stats still rank).
    active = base["active"]
    if active:
        ranked = ranked.filter(pl.col("gsis_id").is_in(active))

    # Drop players who can't help — Out this week, or long-inactive (ranked on
    # stale year-old stats). Questionable/Doubtful stay but get flagged.
    unavailable = _unavailable(injuries)
    if unavailable:
        ranked = ranked.filter(~pl.col("gsis_id").is_in(unavailable))

    # Drop players buried on the depth chart (e.g. RB3+) — their prior-season
    # stats overstate their current role.
    buried = _buried(base["depth"])
    if buried:
        ranked = ranked.filter(~pl.col("gsis_id").is_in(buried))

    ranked = ranked.head(top).select(
        [
            "gsis_id",
            pl.col("player_display_name").alias("name"),
            "position",
            pl.col("ppr_pg").round(1),
            "games",
        ]
    )

    players = []
    for row in ranked.to_dicts():
        p = {k: _num(v) for k, v in row.items()}
        p["injury_status"] = injuries.get(row["gsis_id"])
        players.append(p)
    return {"season": base["season"], "week": base["week"], "players": players}


# Box-score fields we surface in the game log; the front end picks which to show
# per position.
_LOG_COLS = [
    "season",
    "week",
    "opponent_team",
    "fantasy_points_ppr",
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "targets",
    "receptions",
    "receiving_yards",
    "receiving_tds",
]


@app.get("/api/players/{gsis_id}")
def player_detail(gsis_id: str, _user: str = Depends(require_auth)) -> dict:
    """Full profile for one player: bio, the pickup metrics we compute, and a
    per-week game log."""
    base = _base_ranking()
    feats = base["feats"]

    weeks = feats.filter(
        (pl.col("gsis_id") == gsis_id) & (pl.col("week") <= 18)
    ).sort(["season", "week"])
    if weeks.is_empty():
        raise HTTPException(404, "No data for that player")

    latest = weeks.tail(1).to_dicts()[0]

    # Game log newest-first (this season's games on top, then last season's).
    log = weeks.sort(["season", "week"], descending=True).select(
        [c for c in _LOG_COLS if c in weeks.columns]
    )
    game_log = [
        {("opponent" if k == "opponent_team" else k): _num(v) for k, v in row.items()}
        for row in log.to_dicts()
    ]

    # The metrics that drove the ranking (rolling window through the latest week).
    mrow = base["df"].filter(pl.col("gsis_id") == gsis_id)
    if not mrow.is_empty():
        # Player is in the current ranking window — use the exact ranking numbers.
        m = mrow.to_dicts()[0]
        metrics = {
            "opportunity_score": _num(m.get("opportunity_score"), 3),
            "snap_pct": _num(m.get("snap_pct"), 2),
            "target_share": _num(m.get("target_share"), 3),
            "volume_pg": _num(m.get("volume_pg"), 1),
            "ppr_pg": _num(m.get("ppr_pg"), 1),
            "gap_pg": _num(m.get("gap_pg"), 1),
            "games": m.get("games"),
        }
    else:
        # Not in the ranking window (e.g. missed the last weeks of the season).
        # Fall back to their recent form from their last few games so the tiles
        # still populate. Recent Role is a ranking percentile, so it's undefined
        # here.
        recent = weeks.tail(4)
        volume = recent.select(
            (pl.col("targets").fill_null(0) + pl.col("carries").fill_null(0)).alias("v")
        )["v"].mean()
        metrics = {
            "opportunity_score": None,
            "snap_pct": _num(recent["offense_pct"].mean(), 2),
            "target_share": _num(recent["target_share"].mean(), 3),
            "volume_pg": _num(volume, 1),
            "ppr_pg": _num(recent["fantasy_points_ppr"].mean(), 1),
            "gap_pg": _num(recent["points_gap"].mean(), 1),
            "games": recent.height,
        }

    return {
        "gsis_id": gsis_id,
        "name": latest.get("player_display_name"),
        "position": latest.get("position"),
        # Prefer the current-roster team over the (possibly stale) last-game team.
        "team": base["teams"].get(gsis_id) or latest.get("team"),
        "headshot_url": latest.get("headshot_url"),
        "season": base["season"],
        "metrics": metrics,
        "game_log": game_log,
        "injury_status": base["injuries"].get(gsis_id),
        "depth": _depth_label(base["depth"], gsis_id),
    }


_OUTLOOK_SYSTEM = (
    "You are a concise fantasy football advisor for a PPR league. You are given "
    "the user's current roster and one player they are viewing. Each player has a "
    "recent PPR points-per-game average and a 'role' score (0-1 percentile of "
    "recent snap share, volume, and target share). Decide whether the user should "
    "ADD the viewed player (if a free agent) or how to value them (if already "
    "rostered). If adding, name exactly which rostered player to DROP — prefer the "
    "lowest-value player at a position where the roster has surplus depth, and "
    "never drop a clearly superior starter. A player tagged [INJURY: Out] should "
    "not be added; flag Doubtful/Questionable as a risk. Ground every claim in "
    "the numbers provided; do not invent stats. Answer in 3-5 sentences: a clear "
    "verdict, the drop candidate (if any), and brief reasoning."
)


@app.get("/api/leagues/{league_id}/outlook/{gsis_id}")
def outlook(
    league_id: str, gsis_id: str, user: str = Depends(require_auth)
) -> dict:
    """Gemini-generated add/drop recommendation comparing a player to the roster."""
    username = _sleeper_username(user)
    if not GEMINI_API_KEY:
        raise HTTPException(
            503,
            "Fantasy Outlook needs a Gemini API key — add GEMINI_API_KEY to .env "
            "and restart the server.",
        )

    roster = get_user_roster(league_id, username)
    if roster is None:
        raise HTTPException(404, "No roster for this user in that league")

    mapping = _sleeper_to_gsis()
    for player in (*roster["starters"], *roster["bench"]):
        player["gsis_id"] = mapping.get(player["player_id"])

    base = _base_ranking()
    ranked = base["df"]
    feats = base["feats"]
    injuries = base["injuries"]

    def metrics_for(gid: str | None) -> dict | None:
        if not gid:
            return None
        row = ranked.filter(pl.col("gsis_id") == gid)
        if row.is_empty():
            return None
        m = row.to_dicts()[0]
        return {"ppr_pg": _num(m["ppr_pg"], 1), "role": _num(m["opportunity_score"], 2)}

    target_weeks = feats.filter((pl.col("gsis_id") == gsis_id) & (pl.col("week") <= 18))
    if target_weeks.is_empty():
        raise HTTPException(404, "No data for that player")
    latest = target_weeks.tail(1).to_dicts()[0]
    tm = metrics_for(gsis_id)
    target_stat = f"{tm['ppr_pg']} PPR/gm, role {tm['role']}" if tm else "no recent data"
    target_stat += _injury_suffix(injuries, gsis_id)

    roster_gids = {
        p["gsis_id"] for p in (*roster["starters"], *roster["bench"]) if p["gsis_id"]
    }
    status = (
        "already on the user's roster"
        if gsis_id in roster_gids
        else "a free agent the user is considering adding"
    )

    lines = []
    for label, group in (("STARTER", roster["starters"]), ("BENCH", roster["bench"])):
        for p in group:
            m = metrics_for(p["gsis_id"])
            stat = f"{m['ppr_pg']} PPR/gm, role {m['role']}" if m else "no recent data"
            inj = _injury_suffix(injuries, p["gsis_id"])
            lines.append(f"- [{label}] {p['name']} ({p['position']}, {p['team']}): {stat}{inj}")

    target_team = base["teams"].get(gsis_id) or latest.get("team")
    user_msg = (
        f"Viewed player: {latest.get('player_display_name')} "
        f"({latest.get('position')}, {target_team}) — {target_stat}. "
        f"This player is {status}.\n\n"
        "My roster:\n" + "\n".join(lines) + "\n\n"
        "Should I add this player, and if so who should I drop?"
    )

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=_OUTLOOK_SYSTEM,
                # Headroom for the thinking model's reasoning (a cap, not a charge).
                max_output_tokens=4096,
            ),
        )
    except Exception as exc:  # google-genai raises provider-specific errors
        raise HTTPException(502, f"Gemini request failed: {exc}")

    text = (response.text or "").strip()
    return {"text": text}


_CHAT_SYSTEM = (
    "You are a fantasy football waiver-wire assistant for a PPR league, embedded "
    "in a web app. You are given the user's current roster and the top available "
    "(unrostered) players, each with recent PPR points-per-game and a 'role' score "
    "(0-1 percentile of recent snap share, volume, and target share). On the first "
    "message, give a short, skimmable waiver report: the best available pickups "
    "grouped by position (QB, RB, WR, TE), and for the 2-3 best targets, which "
    "rostered player they could drop to add them — prefer the weakest player at a "
    "position of surplus depth, and never drop a clearly superior starter. Use "
    "short lines or bullets. For follow-up questions, answer conversationally and "
    "specifically. Ground every claim in the numbers provided; never invent stats "
    "or players not listed. Some players are tagged [INJURY: Out/Doubtful/"
    "Questionable] — never recommend adding or starting a player tagged Out, and "
    "flag injury risk for Doubtful/Questionable. Respond in plain text — do not "
    "use Markdown symbols like #, *, or **; you may use a leading dash for list "
    "items."
)


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    text: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]


@app.post("/api/leagues/{league_id}/chat")
def chat(
    league_id: str, req: ChatRequest, user: str = Depends(require_auth)
) -> dict:
    """Conversational waiver assistant grounded in the roster + available players."""
    username = _sleeper_username(user)
    if not GEMINI_API_KEY:
        raise HTTPException(
            503,
            "Waiver Assistant needs a Gemini API key — add GEMINI_API_KEY to .env "
            "and restart the server.",
        )
    if not req.messages:
        raise HTTPException(400, "messages must not be empty")

    roster = get_user_roster(league_id, username)
    if roster is None:
        raise HTTPException(404, "No roster for this user in that league")
    mapping = _sleeper_to_gsis()
    for player in (*roster["starters"], *roster["bench"]):
        player["gsis_id"] = mapping.get(player["player_id"])

    base = _base_ranking()
    ranked = base["df"]
    injuries = base["injuries"]

    roster_lines = []
    for label, group in (("STARTER", roster["starters"]), ("BENCH", roster["bench"])):
        for p in group:
            m = _player_metrics(ranked, p["gsis_id"])
            stat = f"{m['ppr_pg']} PPR/gm, role {m['role']}" if m else "no recent data"
            inj = _injury_suffix(injuries, p["gsis_id"])
            roster_lines.append(
                f"- [{label}] {p['name']} ({p['position']}, {p['team']}): {stat}{inj}"
            )

    taken = rostered_gsis_ids(league_id)
    exclude = taken | _unavailable(injuries) | _buried(base["depth"])
    available = ranked.filter(~pl.col("gsis_id").is_in(exclude)) if exclude else ranked
    active = base["active"]
    if active:
        available = available.filter(pl.col("gsis_id").is_in(active))
    waiver_lines = [
        f"- {row['player_display_name']} ({row['position']}): "
        f"{_num(row['ppr_pg'], 1)} PPR/gm, role {_num(row['opportunity_score'], 2)}"
        f"{_injury_suffix(injuries, row['gsis_id'])}"
        for row in available.head(20).to_dicts()
    ]

    system = (
        _CHAT_SYSTEM
        + f"\n\nScoring: PPR. Data is from the {base['season']} season through "
        f"week {base['week']}.\n\n"
        "TOP AVAILABLE PLAYERS (waiver wire):\n" + "\n".join(waiver_lines) + "\n\n"
        "MY ROSTER:\n" + "\n".join(roster_lines)
    )

    contents = [
        {
            "role": "model" if m.role == "assistant" else "user",
            "parts": [{"text": m.text}],
        }
        for m in req.messages
    ]

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                # 3.6-flash is a thinking model — reasoning eats into this budget,
                # so give plenty of headroom or the visible reply gets truncated.
                # (This is a ceiling, not a charge — you pay only for tokens used.)
                max_output_tokens=4096,
            ),
        )
    except Exception as exc:
        raise HTTPException(502, f"Gemini request failed: {exc}")

    return {"text": (response.text or "").strip()}


def _recent_metrics(base: dict, gsis_id: str) -> dict | None:
    """Name, position, and recent metrics for a player (ranking window, or their
    last 4 games if they're outside it). Returns None if there's no data."""
    feats = base["feats"]
    weeks = feats.filter(
        (pl.col("gsis_id") == gsis_id) & (pl.col("week") <= 18)
    ).sort(["season", "week"])
    if weeks.is_empty():
        return None
    latest = weeks.tail(1).to_dicts()[0]

    mrow = base["df"].filter(pl.col("gsis_id") == gsis_id)
    if not mrow.is_empty():
        m = mrow.to_dicts()[0]
        metrics = {
            "opportunity_score": _num(m.get("opportunity_score"), 3),
            "snap_pct": _num(m.get("snap_pct"), 2),
            "target_share": _num(m.get("target_share"), 3),
            "volume_pg": _num(m.get("volume_pg"), 1),
            "ppr_pg": _num(m.get("ppr_pg"), 1),
            "games": m.get("games"),
        }
    else:
        recent = weeks.tail(4)
        volume = recent.select(
            (pl.col("targets").fill_null(0) + pl.col("carries").fill_null(0)).alias("v")
        )["v"].mean()
        metrics = {
            "opportunity_score": None,
            "snap_pct": _num(recent["offense_pct"].mean(), 2),
            "target_share": _num(recent["target_share"].mean(), 3),
            "volume_pg": _num(volume, 1),
            "ppr_pg": _num(recent["fantasy_points_ppr"].mean(), 1),
            "games": recent.height,
        }
    return {
        "name": latest.get("player_display_name"),
        "position": latest.get("position"),
        "metrics": metrics,
    }


_COMPARE_SYSTEM = (
    "You are a fantasy football advisor for a PPR league. You are given two "
    "players with their recent stats: a 'role' score (0-1 recent-usage "
    "percentile), snap %, target share, touches/game, and PPR points/game. "
    "Compare them head-to-head: say who is the better play going forward and "
    "whether the user should swap. If a player is tagged [INJURY: Out], factor "
    "that heavily against them. Ground it in the numbers; be concise (2-4 "
    "sentences), plain text, no markdown."
)


@app.get("/api/leagues/{league_id}/compare/{gsis_a}/{gsis_b}")
def compare(
    league_id: str, gsis_a: str, gsis_b: str, user: str = Depends(require_auth)
) -> dict:
    """Gemini head-to-head verdict between two players."""
    if not GEMINI_API_KEY:
        raise HTTPException(
            503,
            "Comparison verdict needs a Gemini API key — add GEMINI_API_KEY to "
            ".env and restart the server.",
        )

    base = _base_ranking()
    a = _recent_metrics(base, gsis_a)
    b = _recent_metrics(base, gsis_b)
    if a is None or b is None:
        raise HTTPException(404, "One of the players has no data.")

    # Which of them (if any) is on the user's roster.
    taken: set[str] = set()
    linked = get_sleeper_username(user)
    roster = get_user_roster(league_id, linked) if linked else None
    if roster:
        mapping = _sleeper_to_gsis()
        for p in (*roster["starters"], *roster["bench"]):
            gid = mapping.get(p["player_id"])
            if gid:
                taken.add(gid)

    injuries = base["injuries"]

    def describe(snap: dict, gid: str) -> str:
        m = snap["metrics"]
        where = "on my roster" if gid in taken else "a free agent"
        return (
            f"{snap['name']} ({snap['position']}, {where}): role "
            f"{m['opportunity_score']}, snap {m['snap_pct']}, target share "
            f"{m['target_share']}, {m['volume_pg']} touches/gm, {m['ppr_pg']} PPR/gm"
            f"{_injury_suffix(injuries, gid)}"
        )

    user_msg = (
        f"Player A — {describe(a, gsis_a)}.\n"
        f"Player B — {describe(b, gsis_b)}.\n\n"
        "Who's the better play going forward, and should I swap?"
    )

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_msg,
            config=types.GenerateContentConfig(
                system_instruction=_COMPARE_SYSTEM,
                max_output_tokens=4096,
            ),
        )
    except Exception as exc:
        raise HTTPException(502, f"Gemini request failed: {exc}")

    return {"text": (response.text or "").strip()}
