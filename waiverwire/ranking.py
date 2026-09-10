"""
Waiver-wire ranking — step 1: rolling opportunity score.

The opportunity score answers "how good is this player's *role* right now?"
using only usage (not production), over a trailing window of recent weeks.
That's the waiver signal: a rising snap count and target share show up here
before the fantasy points do.

Method, for a given "as of" week:
  1. Take each player's stats over the trailing `lookback` weeks (default 3).
  2. Average their usage stats across the games they played in that window.
  3. Percentile-rank each usage stat WITHIN position group (so a WR is scored
     against other WRs, a RB against other RBs), giving every input a 0-1 scale.
  4. Combine the normalized inputs with the weights below.

The gap / expected-points model is layered on top of this later.
"""

from __future__ import annotations

import polars as pl

from waiverwire.nfl import build_player_week_features

# Component weights for the opportunity score (must sum to 1.0).
W_SNAP = 0.40    # offensive snap share — is he on the field?
W_VOLUME = 0.40  # targets + carries per game — does he touch the ball?
W_SHARE = 0.20   # WOPR — quality of his share of the passing game

# How much the value score leans on opportunity (role) vs. gap (buy-low signal).
# Backtest verdict (see backtest.py): the gap signal does NOT predict future
# scoring at any horizon (correlation ~-0.05), so it's zeroed out of the score.
# gap_pg is still reported as a context column, just not weighted.
W_OPPORTUNITY = 1.0
W_GAP = 0.0

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]


def _pct_rank(col: str) -> pl.Expr:
    """Percentile rank (0-1) of `col` within position group; nulls -> 0."""
    return (
        pl.col(col).rank(method="average").over("position_group")
        / pl.col(col).count().over("position_group")
    ).fill_null(0.0)


def opportunity_score(
    seasons: list[int],
    as_of_week: int | None = None,
    as_of_season: int | None = None,
    window_games: int = 4,
    min_games: int = 1,
    features: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Rank players by recent opportunity — their most recent games played.

    The window is each player's most recent `window_games` games actually played,
    ordered by (season, week). It spans the season boundary automatically: this
    season's games take priority as they arrive, and last season's tail fills the
    rest early on. Byes and missed games don't shrink the sample. Backtesting on
    2025 showed a 4-game window predicts future scoring better than 3.

    Args:
        seasons: seasons present in `features`.
        as_of_week: if given, exclude games after this week (of `as_of_season`) —
            used for backtesting a point in time. If None, use all games played.
        as_of_season: the season `as_of_week` refers to (defaults to the latest).
        window_games: how many of each player's most recent games to average.
        min_games: drop players with fewer than this many games. Defaults to 1 so
            just-emerged breakout players (one big game) still surface — the games
            count is exposed so tiny samples can be judged accordingly.
        features: optional precomputed frame from `build_player_week_features`
            (pass it to avoid recomputing when calling this repeatedly).

    Returns:
        One row per player, sorted by `opportunity_score` descending, with the
        rolling usage inputs and their normalized components kept for inspection.
    """
    if features is None:
        features = build_player_week_features(seasons, include_redzone=False)

    # Order every game by (season, week) so the most recent — this season first,
    # then last season's tail — sort ahead. `_ord` is a single sortable key.
    pool = features.filter(
        (pl.col("week") <= 18) & (pl.col("position").is_in(SKILL_POSITIONS))
    ).with_columns((pl.col("season") * 100 + pl.col("week")).alias("_ord"))

    if as_of_week is not None:
        season = as_of_season if as_of_season is not None else max(seasons)
        pool = pool.filter(pl.col("_ord") <= season * 100 + as_of_week)

    # Keep each player's most recent `window_games` games played.
    window = pool.filter(
        pl.col("_ord").rank("ordinal", descending=True).over("gsis_id") <= window_games
    )

    # Average usage across the games each player actually played in the window.
    # Gap is summed then divided by games so a missed game doesn't inflate it.
    rolling = window.group_by(["gsis_id", "player_display_name", "position", "position_group"]).agg(
        pl.len().alias("games"),
        pl.col("offense_pct").mean().alias("snap_pct"),
        pl.col("targets").mean().alias("targets_pg"),
        pl.col("carries").mean().alias("carries_pg"),
        pl.col("target_share").mean().alias("target_share"),
        pl.col("wopr").mean().alias("wopr"),
        pl.col("fantasy_points_ppr").mean().alias("ppr_pg"),
        pl.col("points_gap").mean().alias("gap_pg"),
    )

    rolling = rolling.filter(pl.col("games") >= min_games)
    rolling = rolling.with_columns(
        (pl.col("targets_pg").fill_null(0) + pl.col("carries_pg").fill_null(0)).alias("volume_pg")
    )

    # Normalize inputs to 0-1 within position group, then weight.
    rolling = rolling.with_columns(
        _pct_rank("snap_pct").alias("c_snap"),
        _pct_rank("volume_pg").alias("c_volume"),
        _pct_rank("wopr").alias("c_share"),
        _pct_rank("gap_pg").alias("c_gap"),  # high rank = most underperformed = buy-low
    )
    rolling = rolling.with_columns(
        (
            W_SNAP * pl.col("c_snap")
            + W_VOLUME * pl.col("c_volume")
            + W_SHARE * pl.col("c_share")
        ).alias("opportunity_score")
    )

    # Value score blends role (opportunity) with the buy-low signal (gap).
    rolling = rolling.with_columns(
        (
            W_OPPORTUNITY * pl.col("opportunity_score")
            + W_GAP * pl.col("c_gap")
        ).alias("value_score")
    )

    return rolling.sort("value_score", descending=True)


if __name__ == "__main__":
    pl.Config.set_tbl_rows(25)
    pl.Config.set_tbl_cols(-1)

    AS_OF = 18  # last regular-season week of 2025
    feats = build_player_week_features([2025], include_redzone=False)

    ranked = opportunity_score([2025], as_of_week=AS_OF, features=feats)

    cols = [
        "player_display_name",
        "position",
        "games",
        pl.col("snap_pct").round(2),
        pl.col("volume_pg").round(1),
        pl.col("ppr_pg").round(1),
        pl.col("gap_pg").round(1),
        pl.col("opportunity_score").round(3),
        pl.col("value_score").round(3),
    ]

    print(f"\nTop 20 by VALUE (opportunity + buy-low gap), weeks {AS_OF-2}-{AS_OF} of 2025:\n")
    print(ranked.select(cols).head(20))

    print("\nBiggest buy-low signals (high opportunity, most underperformed):\n")
    buylow = (
        ranked.filter(pl.col("opportunity_score") > 0.6)
        .sort("gap_pg", descending=True)
        .select(cols)
        .head(15)
    )
    print(buylow)
