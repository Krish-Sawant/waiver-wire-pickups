"""
Waiver targets — rank the players actually AVAILABLE in your Sleeper league.

Ties the ranking (ranking.py) to your league by removing everyone who's already
rostered. Sleeper rosters use Sleeper player ids; we crosswalk those to gsis_id
via nflreadpy's ff_playerids so they line up with the stats.

The league_id is always passed in (by a front end, or as a CLI arg) — it is not
read from .env, so the same code serves any league the user picks.

Usage:
    python waiver.py                 # picks your first in-season league
    python waiver.py <league_id>     # rank a specific league
"""

from __future__ import annotations

import os
import sys

import polars as pl
import requests
from dotenv import load_dotenv

from waiverwire.nfl import (
    build_player_week_features,
    latest_available_season,
    sleeper_gsis_crosswalk,
)
from waiverwire.ranking import opportunity_score
from waiverwire.sleeper import list_leagues

SLEEPER_BASE = "https://api.sleeper.app/v1"


def get_rostered_sleeper_ids(league_id: str) -> list[str]:
    """Every Sleeper player id currently on a roster in the league.

    Returns an empty list before the draft (all rosters empty), in which case
    every player counts as available.
    """
    rosters = requests.get(f"{SLEEPER_BASE}/league/{league_id}/rosters").json()
    ids: list[str] = []
    for roster in rosters:
        ids.extend(roster.get("players") or [])
    return ids


def rostered_gsis_ids(league_id: str) -> set[str]:
    """Rostered Sleeper ids mapped to gsis_id, for filtering the ranking."""
    sleeper_ids = get_rostered_sleeper_ids(league_id)
    if not sleeper_ids:
        return set()

    xw = sleeper_gsis_crosswalk().with_columns(
        pl.col("sleeper_id").cast(pl.Utf8)  # Sleeper roster ids are strings
    )
    matched = xw.filter(pl.col("sleeper_id").is_in(sleeper_ids))
    return set(matched["gsis_id"].to_list())


def rank_available(
    seasons: list[int],
    as_of_week: int,
    league_id: str,
    top: int = 25,
    **kwargs,
) -> pl.DataFrame:
    """Opportunity ranking restricted to players not currently rostered."""
    ranked = opportunity_score(seasons, as_of_week=as_of_week, **kwargs)
    taken = rostered_gsis_ids(league_id)
    if taken:
        ranked = ranked.filter(~pl.col("gsis_id").is_in(taken))
    return ranked.head(top)


def _select_league(username: str, league_id: str | None) -> dict:
    """Resolve which league to rank: an explicit id, else the user's first
    in-season league, else their first league."""
    leagues = list_leagues(username)
    if not leagues:
        raise SystemExit(f"No leagues found for Sleeper user {username!r}.")
    if league_id:
        for lg in leagues:
            if lg["league_id"] == league_id:
                return lg
        raise SystemExit(f"League {league_id} not found among {username!r}'s leagues.")
    in_season = [lg for lg in leagues if lg["status"] == "in_season"]
    return (in_season or leagues)[0]


def main() -> None:
    """CLI: rank available players for a league (arg) or your first in-season one."""
    load_dotenv()
    username = os.getenv("sleeper_username")

    # league_id comes from the CLI (a front end would pass the user's pick),
    # never from .env — so any league works without editing config.
    requested = sys.argv[1] if len(sys.argv) > 1 else None
    league = _select_league(username, requested)
    league_id = league["league_id"]
    print(f"League: {league['name']!r} ({league['status']}, {league['total_rosters']}-team)\n")

    taken = rostered_gsis_ids(league_id)
    if not taken:
        print(
            f"NOTE: no rostered players found for league {league_id} "
            "(league is pre-draft / empty), so every player is treated as "
            "available. Once your draft happens, rostered players drop out "
            "automatically.\n"
        )

    # Auto-detect the newest season nflverse has data for, then use its latest
    # played regular-season week as the "as of" point — no yearly hand-editing.
    data_season = latest_available_season()
    feats = build_player_week_features([data_season], include_redzone=False)
    as_of = int(
        feats.filter(pl.col("week") <= 18)["week"].max()
    )

    targets = rank_available(
        [data_season],
        as_of_week=as_of,
        league_id=league_id,
        top=20,
        features=feats,
    )

    print(f"Top available waiver targets ({data_season}, through week {as_of}):\n")
    print(
        targets.select(
            [
                "player_display_name",
                "position",
                pl.col("snap_pct").round(2),
                pl.col("volume_pg").round(1),
                pl.col("ppr_pg").round(1),
                pl.col("opportunity_score").round(3),
            ]
        )
    )


if __name__ == "__main__":
    main()
