"""
Sleeper account helpers — resolve a user and list the leagues they're in.

This is the data a front end needs on load: given a Sleeper username, show every
league the user belongs to so they can pick one (instead of hardcoding a
league_id). Everything here returns plain dicts/lists so it serializes straight
to JSON for an API/front end.
"""

from __future__ import annotations

import os
from datetime import date

import requests
from dotenv import load_dotenv

SLEEPER_BASE = "https://api.sleeper.app/v1"


def get_user_id(username: str) -> str:
    """Resolve a Sleeper username to its stable numeric user id."""
    user = requests.get(f"{SLEEPER_BASE}/user/{username}").json()
    if not user or "user_id" not in user:
        raise ValueError(f"Sleeper user not found: {username!r}")
    return user["user_id"]


def list_leagues(username: str, season: int | None = None) -> list[dict]:
    """Every NFL league a user is in for a season, newest-usable season by default.

    Sleeper organizes leagues by season year. Early in a new year the user may
    have no leagues created for it yet, so if the requested season is empty we
    fall back one year.

    Returns a list of dicts with the fields a front end needs to render a picker.
    """
    user_id = get_user_id(username)
    start = season if season is not None else date.today().year

    for yr in (start, start - 1):
        raw = requests.get(
            f"{SLEEPER_BASE}/user/{user_id}/leagues/nfl/{yr}"
        ).json()
        if raw:
            return [_league_summary(lg) for lg in raw]
    return []


def _league_summary(lg: dict) -> dict:
    """Trim a raw Sleeper league object to the fields a UI actually uses."""
    return {
        "league_id": lg.get("league_id"),
        "name": (lg.get("name") or "").strip(),
        "season": lg.get("season"),
        "status": lg.get("status"),          # pre_draft / drafting / in_season / complete
        "total_rosters": lg.get("total_rosters"),
        "sport": lg.get("sport"),
        "avatar": lg.get("avatar"),          # avatar id; UI can build the image URL
        "scoring": (lg.get("scoring_settings") or {}).get("rec"),  # ~1.0 PPR, 0.5 half, 0 standard
    }


def main() -> None:
    """CLI: list every league for the Sleeper user named in .env."""
    load_dotenv()
    username = os.getenv("sleeper_username")

    leagues = list_leagues(username)
    print(f"Leagues for {username!r}:\n")
    for lg in leagues:
        ppr = {1.0: "PPR", 0.5: "Half-PPR"}.get(lg["scoring"], "Standard")
        print(
            f"  {lg['league_id']}  {lg['name']!r:32s} "
            f"{lg['season']} {lg['status']:10s} "
            f"{lg['total_rosters']}-team {ppr}"
        )


if __name__ == "__main__":
    main()
