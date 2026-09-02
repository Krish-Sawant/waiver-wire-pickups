import nflreadpy as nfl

# Fetch players Fantasy points
# Fetch players Targets / receptions
# Rushing yards / carries (for RB)
# Passing yards / TDs / INTs (for QB)
# Snap %
# Target share
# Red zone touches
# Air yards
# Opponent's defense rank
# Upcoming schedule
# Injury status
# Bye weeks


weekly_player_stats  = nfl.load_player_stats([2021,2022,2023,2024,2025])
weekly_schedules = nfl.load_schedules([2026])
player_depth = nfl.load_depth_charts([2026])
#player_snap_count = nfl.load_snap_counts([2026])

print(weekly_player_stats)
print(weekly_schedules)
print(player_depth)