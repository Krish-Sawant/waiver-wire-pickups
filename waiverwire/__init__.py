"""waiverwire — rank fantasy-football waiver targets from Sleeper + nflverse data.

Modules:
    nfl      data layer: weekly player features from nflreadpy
    sleeper  Sleeper account/league/roster access
    ranking  rolling opportunity score (validated in tests/backtest.py)
    waiver   pipeline tying it together: rank the players available in a league

Imports are kept lazy (import the submodule you need) so `import waiverwire`
stays cheap.
"""

__version__ = "0.1.0"
