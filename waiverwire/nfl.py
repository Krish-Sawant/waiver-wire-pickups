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


def latest_rankable_season(min_weeks: int = 4) -> int:
    """Newest season with enough games played to rank on.

    `latest_available_season` flips to a new season as soon as its first week is
    published, but one or two weeks is too small a sample to rank (with a 3-week
    window and a 2-game minimum, everyone gets filtered out). Until the new
    season has `min_weeks` of regular-season data, stay on the prior season.
    """
    season = latest_available_season()
    try:
        weeks = nfl.load_player_stats([season]).filter(pl.col("week") <= 18)["week"]
        max_week = weeks.max() if weeks.len() else 0
    except Exception:
        max_week = 0
    if max_week is None or max_week < min_weeks:
        return season - 1
    return season


def active_roster_ids(season: int) -> set[str]:
    """gsis_ids of players on an active NFL roster (status ACT) for a season.

    Used to keep retired / cut / unsigned players off the waiver board even when
    their prior-season stats still look good. Returns an empty set if the roster
    file isn't available — callers should then skip the filter rather than drop
    everyone.
    """
    try:
        rosters = nfl.load_rosters([season])
    except Exception:
        return set()
    if "status" in rosters.columns:
        rosters = rosters.filter(pl.col("status") == "ACT")
    return set(
        rosters.filter(pl.col("gsis_id").is_not_null())["gsis_id"].to_list()
    )


def depth_positions(season: int) -> dict[str, dict]:
    """gsis_id -> {'pos': 'RB', 'rank': 3} — the player's spot on the current
    depth chart at their (best) fantasy position.

    Lets the ranking avoid promoting a buried backup whose prior-season stats
    still look good (e.g. an RB who started when the starter was hurt but is now
    third string). Uses the latest live depth-chart snapshot.
    """
    try:
        dc = nfl.load_depth_charts([season])
    except Exception:
        return {}
    needed = {"dt", "gsis_id", "pos_abb", "pos_rank"}
    if not needed.issubset(dc.columns):
        return {}

    latest = dc.filter(pl.col("dt") == dc["dt"].max())
    fantasy = latest.filter(
        pl.col("pos_abb").is_in(["QB", "RB", "WR", "TE"])
        & pl.col("gsis_id").is_not_null()
    )
    # Best (lowest) rank per player across fantasy positions.
    best = fantasy.sort("pos_rank").group_by("gsis_id").first()
    return {
        row["gsis_id"]: {"pos": row["pos_abb"], "rank": row["pos_rank"]}
        for row in best.select(["gsis_id", "pos_abb", "pos_rank"]).to_dicts()
    }


def current_teams(season: int) -> dict[str, str]:
    """gsis_id -> current NFL team for a season, from the roster file.

    The game log shows the team a player suited up for *last game*, which is
    stale after an offseason move (e.g. a player who left the 49ers for the
    Vikings). The roster has their current team.
    """
    try:
        rosters = nfl.load_rosters([season])
    except Exception:
        return {}
    r = rosters.filter(
        pl.col("gsis_id").is_not_null() & pl.col("team").is_not_null()
    )
    return dict(zip(r["gsis_id"].to_list(), r["team"].to_list()))


def current_season() -> int:
    """The current NFL season year — always the season rosters, depth charts, and
    injury reports should come from.

    The league year rolls over in March, so January/February still belong to the
    prior season (e.g. the 2025 playoffs happen in early 2026).
    """
    today = date.today()
    return today.year if today.month >= 3 else today.year - 1


def rankable_seasons() -> list[int]:
    """The seasons to load for ranking: the latest published season plus the one
    before it.

    Loading both lets the "last N games played" window span the season boundary —
    the current season's games take priority as they arrive, and last season fills
    the rest early on (when only a game or two of the new season exists).
    """
    latest = latest_available_season()
    return [latest - 1, latest]

# Columns from load_player_stats that actually matter for fantasy/waiver ranking.
# (The raw table has ~150 columns, most of them defense/kicking/punting noise.)
_STAT_COLS = [
    "player_id",
    "player_display_name",
    "headshot_url",
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


def get_current_injuries(seasons: list[int], stale_weeks: int = 4) -> dict[str, str]:
    """Each player's current availability flag: gsis_id -> status.

    Two signals are combined so we don't recommend players who can't help:

    1. Injury reports: the player's latest report (Out / Doubtful / Questionable),
       but only if they haven't played since it — this captures a late-2025 IR
       stint that persists into today.
    2. Staleness ("Inactive"): a player whose most recent game is more than
       `stale_weeks` football-weeks behind the current week. This catches
       season-ending injuries that never appeared on an injury report — e.g. a
       player who last played 2025 Week 4 and hasn't played since would otherwise
       rank on year-old stats.

    Injury-report status takes priority; staleness fills the gaps.
    """
    reg = 18  # regular-season length, for spanning the season boundary
    latest_season = current_season()  # rosters + injury reports come from here

    stats = (
        nfl.load_player_stats(seasons)
        .select(pl.col("player_id").alias("gsis_id"), "season", "week")
        .with_columns((pl.col("season") * 100 + pl.col("week")).alias("ord"))
    )
    if stats.is_empty():
        return {}

    # The current point = the most recent (season, week) anyone has played.
    cur = stats.sort("ord").tail(1).to_dicts()[0]
    cur_season, cur_week = cur["season"], cur["week"]

    # Each player's most recent game, and how many football-weeks ago it was.
    last_game = stats.sort("ord").group_by("gsis_id").tail(1)
    last_game = last_game.with_columns(
        pl.when(pl.col("season") == cur_season)
        .then(cur_week - pl.col("week"))
        .otherwise(
            (reg - pl.col("week"))
            + cur_week
            + (cur_season - pl.col("season") - 1) * reg
        )
        .alias("weeks_since")
    )

    # Current-season roster status — the source of truth for "is he healthy now".
    roster_status: dict[str, str] = {}
    try:
        rosters = nfl.load_rosters([latest_season])
        if "status" in rosters.columns:
            roster_status = dict(
                zip(rosters["gsis_id"].to_list(), rosters["status"].to_list())
            )
    except Exception:
        pass
    active = {gid for gid, s in roster_status.items() if s == "ACT"}

    status: dict[str, str] = {}

    # 1) CURRENT-season injury reports only (this week's Out/Doubtful/Questionable).
    #    Older seasons' reports are stale — a 2025 "Out" says nothing about today.
    inj = (
        nfl.load_injuries([latest_season])
        .select(
            "gsis_id",
            pl.col("season").cast(pl.Int32),
            pl.col("week").cast(pl.Int32),
            "report_status",
        )
        .filter(pl.col("report_status").is_not_null() & pl.col("gsis_id").is_not_null())
        .with_columns((pl.col("season") * 100 + pl.col("week")).alias("ord"))
    )
    if not inj.is_empty():
        latest = inj.sort("ord").group_by("gsis_id").tail(1)
        last_ord = last_game.select("gsis_id", pl.col("ord").alias("last_ord"))
        current = latest.join(last_ord, on="gsis_id", how="left").filter(
            pl.col("last_ord").is_null() | (pl.col("ord") >= pl.col("last_ord"))
        )
        status.update(
            zip(current["gsis_id"].to_list(), current["report_status"].to_list())
        )

    # 2) Reserve/IR roster designations -> Out (season-long injuries that may not
    #    be on a weekly report).
    for gid, rstatus in roster_status.items():
        if gid not in status and rstatus in {"RES", "PUP", "NON", "IR"}:
            status[gid] = "Out"

    # 3) Staleness -> Inactive, but NEVER for an active-roster player. An ACT
    #    player who was hurt in 2025 and has since recovered (e.g. hasn't logged a
    #    2026 game yet) stays unflagged.
    stale = last_game.filter(pl.col("weeks_since") > stale_weeks)
    for gid in stale["gsis_id"].to_list():
        if gid not in status and gid not in active:
            status[gid] = "Inactive"

    return status


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

    ffopportunity lags the core stats — early in a season its file may not exist
    yet. Since expected points only feed the (unweighted) gap metric, we degrade
    to an empty frame rather than failing the whole feature build.
    """
    empty = pl.DataFrame(
        schema={
            "gsis_id": pl.Utf8,
            "season": pl.Int32,
            "week": pl.Int32,
            "actual_points": pl.Float64,
            "expected_points": pl.Float64,
            "points_gap": pl.Float64,
        }
    )
    # Load per-season and skip any that 404 (e.g. the current season before
    # ffopportunity has published it), so one missing season doesn't drop the
    # others.
    frames = []
    for season in seasons:
        try:
            o = nfl.load_ff_opportunity([season]).rename({"player_id": "gsis_id"})
        except Exception:
            continue
        frames.append(
            o.select(
                [
                    "gsis_id",
                    # ffopportunity ships season as str and week as float; align
                    # with the integer keys used everywhere else.
                    pl.col("season").cast(pl.Int32),
                    pl.col("week").cast(pl.Int32),
                    pl.col("total_fantasy_points").alias("actual_points"),
                    pl.col("total_fantasy_points_exp").alias("expected_points"),
                ]
            ).with_columns(
                (pl.col("expected_points") - pl.col("actual_points")).alias("points_gap")
            )
        )
    return pl.concat(frames) if frames else empty


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
