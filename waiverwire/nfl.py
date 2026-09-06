"""
Data layer for waiver-wire player ranking.

Everything is keyed on `gsis_id` (nflverse's canonical player id, e.g.
"00-0034796"). Different nflreadpy datasets ship with different id systems, so
this module normalizes them all back to `gsis_id`:

    load_player_stats  -> player_id   (already gsis)
    load_injuries      -> gsis_id
    load_depth_charts  -> gsis_id
    load_snap_counts   -> pfr_player_id  (crosswalked via load_players)
    Sleeper rosters    -> sleeper_id     (crosswalked via load_ff_playerids)

The public entry point is `build_player_week_features(seasons)`, which returns
one row per (gsis_id, season, week) with all the features used for ranking.

All functions return polars DataFrames. nflreadpy caches downloads locally, so
repeated calls in a session are cheap.
"""

from __future__ import annotations

from datetime import date

import nflreadpy as nfl
import polars as pl
import requests

# nflverse publishes weekly player stats as one parquet per season. We probe
# this URL to find the newest season that actually exists yet.
_STATS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "stats_player/stats_player_week_{season}.parquet"
)


def latest_available_season(probe_from: int | None = None) -> int:
    """Newest season nflverse has published weekly stats for.

    Early in a new NFL year the current season's file doesn't exist yet (games
    haven't been played), so we walk backwards from the current calendar year
    until a season's file responds 200. Uses a cheap HEAD request, no download.
    """
    start = probe_from if probe_from is not None else date.today().year
    for season in range(start, start - 3, -1):
        try:
            resp = requests.head(
                _STATS_URL.format(season=season), allow_redirects=True, timeout=15
            )
            if resp.status_code == 200:
                return season
        except requests.RequestException:
            continue
    # Fall back to the earliest probed season rather than raising; the caller
    # will get a clear error from nflreadpy if it truly can't load anything.
    return start - 2

# Columns from load_player_stats that actually matter for fantasy/waiver ranking.
# (The raw table has ~150 columns, most of them defense/kicking/punting noise.)
_STAT_COLS = [
    "player_id",
    "player_display_name",
    "position",
    "position_group",
    "season",
    "week",
    "team",
    "opponent_team",
    # passing (QB)
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "passing_interceptions",
    # rushing (RB)
    "carries",
    "rushing_yards",
    "rushing_tds",
    # receiving (WR/TE/RB)
    "targets",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "target_share",
    "air_yards_share",
    "wopr",
    # fantasy output
    "fantasy_points",
    "fantasy_points_ppr",
]


def get_player_week_stats(seasons: list[int]) -> pl.DataFrame:
    """Weekly per-player box-score stats, trimmed to fantasy-relevant columns.

    Renames `player_id` -> `gsis_id` so it joins with everything else.
    """
    df = nfl.load_player_stats(seasons)
    df = df.select([c for c in _STAT_COLS if c in df.columns])
    return df.rename({"player_id": "gsis_id"})


def _pfr_to_gsis() -> pl.DataFrame:
    """Crosswalk mapping Pro-Football-Reference ids to gsis ids."""
    players = nfl.load_players()
    return (
        players.select(["gsis_id", "pfr_id"])
        .filter(pl.col("pfr_id").is_not_null() & pl.col("gsis_id").is_not_null())
        .unique(subset=["pfr_id"])
    )


def get_snap_counts(seasons: list[int]) -> pl.DataFrame:
    """Weekly snap counts with `gsis_id` attached.

    Returns offense snap share (`offense_pct`) which is the key usage signal for
    waiver pickups — a player suddenly playing 70%+ of snaps is a breakout tell.
    """
    snaps = nfl.load_snap_counts(seasons).rename({"pfr_player_id": "pfr_id"})
    snaps = snaps.join(_pfr_to_gsis(), on="pfr_id", how="left")
    return snaps.select(
        [
            "gsis_id",
            "season",
            "week",
            "team",
            "offense_snaps",
            "offense_pct",
        ]
    )


def get_injuries(seasons: list[int]) -> pl.DataFrame:
    """Weekly injury report. `report_status` is Out / Doubtful / Questionable / None."""
    inj = nfl.load_injuries(seasons)
    return inj.select(
        [
            "gsis_id",
            "season",
            "week",
            "report_status",
            "report_primary_injury",
            "practice_status",
        ]
    )


def get_redzone_touches(seasons: list[int]) -> pl.DataFrame:
    """Red-zone (inside opponent's 20) touches per player per week, from pbp.

    A "touch" is a carry (rusher) or a target (intended receiver). Red-zone
    volume is a strong predictor of touchdown upside. NOTE: pbp is large
    (~50MB/season) so this is the heaviest call in the module.
    """
    pbp = nfl.load_pbp(seasons)
    rz = pbp.filter(pl.col("yardline_100") <= 20)

    rush = (
        rz.filter(pl.col("rush_attempt") == 1)
        .select(["season", "week", pl.col("rusher_player_id").alias("gsis_id")])
        .drop_nulls("gsis_id")
    )
    rec = (
        rz.filter(pl.col("pass_attempt") == 1)
        .select(["season", "week", pl.col("receiver_player_id").alias("gsis_id")])
        .drop_nulls("gsis_id")
    )

    touches = pl.concat([rush, rec])
    return touches.group_by(["gsis_id", "season", "week"]).agg(
        pl.len().alias("redzone_touches")
    )


def get_expected_points(seasons: list[int]) -> pl.DataFrame:
    """Weekly actual vs. expected fantasy points, from ffopportunity.

    Expected points ("_exp") model what a typical player scores given a player's
    exact usage — carries, targets, air yards, and field position — independent
    of whether the ball actually went in. Comparing to what he *did* score
    reveals luck/inefficiency:

    `points_gap` = expected - actual
        > 0  -> UNDERperformed his usage (unlucky/inefficient -> buy-low)
        < 0  -> OVERperformed his usage (lucky -> regression-down risk)

    Uses ffopportunity's default (non-PPR) scoring; `actual` and `expected` use
    the same scoring, so the gap is internally consistent.
    """
    o = nfl.load_ff_opportunity(seasons).rename({"player_id": "gsis_id"})
    o = o.select(
        [
            "gsis_id",
            # ffopportunity ships season as str and week as float; align with
            # the integer keys used everywhere else so joins don't break.
            pl.col("season").cast(pl.Int32),
            pl.col("week").cast(pl.Int32),
            pl.col("total_fantasy_points").alias("actual_points"),
            pl.col("total_fantasy_points_exp").alias("expected_points"),
        ]
    )
    return o.with_columns(
        (pl.col("expected_points") - pl.col("actual_points")).alias("points_gap")
    )


def get_defense_ranks(seasons: list[int]) -> pl.DataFrame:
    """Season-to-date opponent-defense strength, by position.

    For each defense, we sum the PPR points it allows to each position, then
    accumulate week-over-week (so week N reflects only weeks 1..N-1 of allowance,
    i.e. no lookahead leakage) and rank all 32 defenses within each position.

    `def_rank` == 1  -> allows the MOST points to that position (softest matchup)
    `def_rank` == 32 -> allows the FEWEST points (toughest matchup)

    The returned frame is keyed by (defense_team, position, season, week) and is
    meant to be joined on a player's `opponent_team`.
    """
    stats = nfl.load_player_stats(seasons).select(
        ["opponent_team", "position", "season", "week", "fantasy_points_ppr"]
    )

    # Points each defense allowed to each position, per week.
    weekly_allowed = (
        stats.drop_nulls(["opponent_team", "position"])
        .group_by(["opponent_team", "position", "season", "week"])
        .agg(pl.col("fantasy_points_ppr").sum().alias("pts_allowed"))
    )

    # Cumulative allowance BEFORE the current week (shifted so week N excludes N).
    weekly_allowed = weekly_allowed.sort(["opponent_team", "position", "season", "week"])
    weekly_allowed = weekly_allowed.with_columns(
        pl.col("pts_allowed")
        .cum_sum()
        .shift(1)
        .over(["opponent_team", "position", "season"])
        .alias("pts_allowed_to_date")
    )

    # Rank defenses within (season, week, position); 1 = softest matchup.
    weekly_allowed = weekly_allowed.with_columns(
        pl.col("pts_allowed_to_date")
        .rank(method="min", descending=True)
        .over(["season", "week", "position"])
        .alias("def_rank")
    )

    return weekly_allowed.select(
        [
            pl.col("opponent_team").alias("defense_team"),
            "position",
            "season",
            "week",
            "pts_allowed_to_date",
            "def_rank",
        ]
    )


def get_bye_weeks(season: int) -> pl.DataFrame:
    """Bye week per team for a season, derived from the schedule.

    A team's bye is the regular-season week in which it does not appear.
    """
    sched = nfl.load_schedules([season]).filter(pl.col("game_type") == "REG")

    played = pl.concat(
        [
            sched.select(["season", "week", pl.col("home_team").alias("team")]),
            sched.select(["season", "week", pl.col("away_team").alias("team")]),
        ]
    ).unique()

    reg_weeks = sched.select("week").unique()["week"].to_list()

    # For each team, the regular-season week missing from its played weeks.
    teams = played.select("team").unique()["team"].to_list()
    rows = []
    for team in teams:
        weeks_played = set(
            played.filter(pl.col("team") == team)["week"].to_list()
        )
        bye = [w for w in reg_weeks if w not in weeks_played]
        rows.append({"season": season, "team": team, "bye_week": bye[0] if bye else None})

    return pl.DataFrame(rows)


def get_upcoming_matchups(season: int, week: int) -> pl.DataFrame:
    """Each team's opponent for a given (season, week), long format.

    Returns rows of (season, week, team, opponent, is_home). Join a player's
    `team` to get the defense they're about to face, then join `get_defense_ranks`
    on that opponent to score the matchup.
    """
    sched = nfl.load_schedules([season]).filter(pl.col("week") == week)

    home = sched.select(
        [
            "season",
            "week",
            pl.col("home_team").alias("team"),
            pl.col("away_team").alias("opponent"),
            pl.lit(True).alias("is_home"),
        ]
    )
    away = sched.select(
        [
            "season",
            "week",
            pl.col("away_team").alias("team"),
            pl.col("home_team").alias("opponent"),
            pl.lit(False).alias("is_home"),
        ]
    )
    return pl.concat([home, away])


def sleeper_gsis_crosswalk() -> pl.DataFrame:
    """Map Sleeper player ids to gsis ids so league rosters join to stats.

    Sleeper's roster/matchup endpoints return `player_id` values that are Sleeper
    ids; this bridges them to everything else in this module.
    """
    xw = nfl.load_ff_playerids()
    return (
        xw.select(["sleeper_id", "gsis_id", "name", "position", "team"])
        .filter(pl.col("sleeper_id").is_not_null() & pl.col("gsis_id").is_not_null())
        .unique(subset=["sleeper_id"])
    )


def build_player_week_features(
    seasons: list[int], include_redzone: bool = True
) -> pl.DataFrame:
    """One row per (gsis_id, season, week) with all ranking features joined.

    Columns include box-score stats, target share, offensive snap %, red-zone
    touches, weekly injury status, and the season-to-date defense rank of the
    opponent the player faced that week.

    Set `include_redzone=False` to skip the heavy pbp download.
    """
    base = get_player_week_stats(seasons)

    snaps = get_snap_counts(seasons).drop("team")  # team already on base
    base = base.join(snaps, on=["gsis_id", "season", "week"], how="left")

    inj = get_injuries(seasons)
    base = base.join(inj, on=["gsis_id", "season", "week"], how="left")

    exp = get_expected_points(seasons)
    base = base.join(exp, on=["gsis_id", "season", "week"], how="left")

    if include_redzone:
        rz = get_redzone_touches(seasons)
        base = base.join(rz, on=["gsis_id", "season", "week"], how="left")
        base = base.with_columns(pl.col("redzone_touches").fill_null(0))

    # Attach the opponent's defense rank vs this player's position.
    dranks = get_defense_ranks(seasons)
    base = base.join(
        dranks,
        left_on=["opponent_team", "position", "season", "week"],
        right_on=["defense_team", "position", "season", "week"],
        how="left",
    )

    return base.sort(["season", "week", "fantasy_points_ppr"], descending=[False, False, True])


if __name__ == "__main__":
    pl.Config.set_tbl_cols(-1)

    # Quick smoke test on the most recent completed season.
    feats = build_player_week_features([2025], include_redzone=True)
    print("feature table shape:", feats.shape)
    print(feats.columns)

    # Top waiver-relevant usage in week 1 (WR/RB/TE), sorted by PPR.
    demo = (
        feats.filter((pl.col("week") == 1) & (pl.col("position_group") == "WR"))
        .select(
            [
                "player_display_name",
                "team",
                "opponent_team",
                "targets",
                "target_share",
                "offense_pct",
                "redzone_touches",
                "def_rank",
                "fantasy_points_ppr",
            ]
        )
        .head(10)
    )
    print(demo)
