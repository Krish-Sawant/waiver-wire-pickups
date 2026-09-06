"""
Backtest — does the ranking actually predict future scoring?

The worry: the model recommends on opportunity, so it can flag a player who
just scored 5 points. Is that smart (he's due) or dumb (he's just bad)?

To answer it honestly we do a walk-forward test with NO lookahead:
  For each week W in the season:
    1. Rank every player using only data through week W.
    2. Look at what they ACTUALLY scored in weeks W+1 .. W+FORWARD
       (points the model never saw).
    3. Pool all (week, player) rows across the season.

Then we ask two questions:
  A. Does a higher score predict more future points? (rank correlation)
  B. THE KEY ONE: among players who scored LOW recently, do the ones the model
     likes actually bounce back more than the ones it doesn't? If yes, "pick up
     this 5-point player" is a real signal, not noise.
"""

from __future__ import annotations

import polars as pl

from waiverwire.nfl import build_player_week_features
from waiverwire.ranking import opportunity_score

FORWARD = 2       # how many weeks ahead we measure actual scoring
LOW_SCORE = 8.0   # PPR/game threshold that defines a "low recent scorer"


def _future_points(features: pl.DataFrame, season: int, start: int, end: int) -> pl.DataFrame:
    """Mean actual PPR/game for each player over weeks [start, end]."""
    return (
        features.filter(
            (pl.col("season") == season)
            & (pl.col("week") >= start)
            & (pl.col("week") <= end)
        )
        .group_by("gsis_id")
        .agg(pl.col("fantasy_points_ppr").mean().alias("future_ppr"))
    )


def run_backtest(season: int, weeks: range) -> pl.DataFrame:
    """Walk forward through `weeks`, pairing each week's ranking with what
    actually happened next. Returns one row per (as_of_week, player)."""
    feats = build_player_week_features([season], include_redzone=False)

    snapshots = []
    for w in weeks:
        ranked = opportunity_score([season], as_of_week=w, features=feats)
        future = _future_points(feats, season, w + 1, w + FORWARD)
        merged = ranked.join(future, on="gsis_id", how="inner").with_columns(
            pl.lit(w).alias("as_of_week")
        )
        snapshots.append(
            merged.select(
                [
                    "as_of_week",
                    "player_display_name",
                    "position",
                    "ppr_pg",          # what he scored recently (the input)
                    "opportunity_score",
                    "gap_pg",
                    "value_score",
                    "future_ppr",      # what he scored next (the truth)
                ]
            )
        )
    return pl.concat(snapshots)


def _spearman(df: pl.DataFrame, predictor: str, target: str = "future_ppr") -> float:
    return df.select(pl.corr(predictor, target, method="spearman")).item()


if __name__ == "__main__":
    pl.Config.set_tbl_rows(20)

    season = 2025
    bt = run_backtest(season, weeks=range(4, 16))
    print(f"Backtest on {season}: {bt.height} (week, player) predictions\n")

    # --- Question A: does each signal predict future scoring? ---
    print("How well each signal predicts next-2-week PPR (rank correlation, higher = better):")
    for name in ["ppr_pg", "opportunity_score", "gap_pg", "value_score"]:
        label = {
            "ppr_pg": "recent points only (naive baseline)",
            "opportunity_score": "opportunity score",
            "gap_pg": "gap (buy-low) alone",
            "value_score": "value score (the model)",
        }[name]
        print(f"  {label:38s}: {_spearman(bt, name):+.3f}")

    # --- Question B: the buy-low acid test ---
    # Among players who scored LOW recently, split by opportunity and compare
    # what they ACTUALLY did next.
    low = bt.filter(pl.col("ppr_pg") < LOW_SCORE)
    med = low["opportunity_score"].median()
    low = low.with_columns(
        pl.when(pl.col("opportunity_score") >= med)
        .then(pl.lit("model LIKES (high opp)"))
        .otherwise(pl.lit("model PASSES (low opp)"))
        .alias("bucket")
    )
    print(
        f"\nAcid test — players who scored < {LOW_SCORE} PPR recently "
        f"({low.height} cases).\nDid the ones the model liked actually bounce back?\n"
    )
    summary = (
        low.group_by("bucket")
        .agg(
            pl.len().alias("n"),
            pl.col("ppr_pg").mean().round(1).alias("recent_ppr"),
            pl.col("future_ppr").mean().round(1).alias("actual_next_ppr"),
        )
        .sort("recent_ppr")
    )
    print(summary)
