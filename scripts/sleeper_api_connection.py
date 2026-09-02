import os
import requests
from dotenv import load_dotenv

# TODO 
# 1. Fetch all the leagues NAMES, leagues ID and settings of the league
# 2. Fetch the current Season and have it update by itself
# 3. Fetch the Users current roster
load_dotenv()

USERNAME = os.getenv("sleeper_username")

user = requests.get(f"https://api.sleeper.app/v1/user/{USERNAME}").json()
USER_ID = user["user_id"]

SEASON = os.getenv("season")
user_leagues = requests.get(f"https://api.sleeper.app/v1/user/{USER_ID}/leagues/nfl/{SEASON}").json()


LEAGUE_ID = os.getenv("league_id")
user_league_rosters = requests.get(f"https://api.sleeper.app/v1/league/{LEAGUE_ID}/rosters").json()
print("League ID:", LEAGUE_ID)


user_league_matchups = requests.get(f"https://api.sleeper.app/v1/league/{LEAGUE_ID}/matchups/{SEASON}").json()

print(user_league_rosters)

