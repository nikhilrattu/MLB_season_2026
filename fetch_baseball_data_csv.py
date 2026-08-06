"""
Pull current-season MLB game data into a CSV shaped like IPL.csv
(one row per completed game: venue, teams, winner, margin, top
performers) using MLB's free, keyless Stats API.

No API key required. Data source: statsapi.mlb.com (the same API
that powers MLB.com).

Usage:
    pip install requests
    python fetch_mlb_data.py
    python fetch_mlb_data.py --start-date 2026-03-25 --end-date 2026-08-01
    python fetch_mlb_data.py --output mlb_2026.csv --workers 16

By default it pulls from the start of the 2026 regular season
through today, so re-running it later just picks up newly played
games. Per-game data (decisions + boxscore) is fetched concurrently
with a thread pool, since each game needs 2 extra API calls and the
slow part is network round-trip time, not local processing.
"""

import argparse
import csv
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import requests

BASE_URL = "https://statsapi.mlb.com/api/v1"
LIVE_FEED_URL = "https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
BOXSCORE_URL = "https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"

FIELDNAMES = [
    "game_id",
    "date",
    "venue",
    "home_team",
    "away_team",
    "game_type",
    "home_score",
    "away_score",
    "winner",
    "loser",
    "won_by",       # "Home" or "Away"
    "margin",       # run difference
    "winning_pitcher",
    "losing_pitcher",
    "save_pitcher",
    "top_hitter",
    "top_hitter_team",
    "top_hitter_line",   # e.g. "3-4, 2 HR, 4 RBI"
    "top_pitcher",
    "top_pitcher_team",
    "top_pitcher_line",  # e.g. "7.0 IP, 10 K, 1 ER"
]

# One session, reused across threads, with a connection pool sized
# for concurrent workers -- this is what actually saves the time
# (TCP/TLS handshake reuse), not just the parallelism itself.
def make_session(pool_size):
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
    session.mount("https://", adapter)
    return session


def get_schedule(session, start_date, end_date):
    """Return a list of completed game dicts (gamePk, date, venue, teams)."""
    params = {
        "sportId": 1,  # MLB
        "startDate": start_date,
        "endDate": end_date,
        "gameType": "R",  # regular season only; drop this filter for postseason too
    }
    resp = session.get(f"{BASE_URL}/schedule", params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    games = []
    for day in data.get("dates", []):
        for g in day.get("games", []):
            if g.get("status", {}).get("abstractGameState") != "Final":
                continue  # skip games not yet played
            games.append(
                {
                    "game_pk": g["gamePk"],
                    "date": g["officialDate"],
                    "venue": g.get("venue", {}).get("name", ""),
                    "game_type": g.get("gameType", ""),
                    "home_team": g["teams"]["home"]["team"]["name"],
                    "away_team": g["teams"]["away"]["team"]["name"],
                    "home_score": g["teams"]["home"].get("score"),
                    "away_score": g["teams"]["away"].get("score"),
                }
            )
    return games


def get_decisions(session, game_pk):
    """Winning/losing/save pitcher names from the live feed's decisions block."""
    resp = session.get(LIVE_FEED_URL.format(game_pk=game_pk), timeout=30)
    resp.raise_for_status()
    decisions = resp.json().get("liveData", {}).get("decisions", {})
    return {
        "winning_pitcher": decisions.get("winner", {}).get("fullName", ""),
        "losing_pitcher": decisions.get("loser", {}).get("fullName", ""),
        "save_pitcher": decisions.get("save", {}).get("fullName", ""),
    }


def get_top_performers(session, game_pk, home_team, away_team):
    """
    Pull the boxscore and pick:
      - top hitter across both teams, ranked by hits then home runs
      - top pitcher across both teams, ranked by strikeouts (min 1 IP)
    """
    resp = session.get(BOXSCORE_URL.format(game_pk=game_pk), timeout=30)
    resp.raise_for_status()
    box = resp.json()

    top_hitter = None
    top_pitcher = None

    for side, team_name in (("home", home_team), ("away", away_team)):
        players = box.get("teams", {}).get(side, {}).get("players", {})
        for p in players.values():
            person_name = p.get("person", {}).get("fullName", "")
            batting = p.get("stats", {}).get("batting", {})
            pitching = p.get("stats", {}).get("pitching", {})

            hits = batting.get("hits", 0) or 0
            if hits or batting.get("homeRuns", 0):
                candidate = {
                    "name": person_name,
                    "team": team_name,
                    "hits": hits,
                    "at_bats": batting.get("atBats", 0),
                    "home_runs": batting.get("homeRuns", 0),
                    "rbi": batting.get("rbi", 0),
                }
                if top_hitter is None or (
                    candidate["hits"],
                    candidate["home_runs"],
                    candidate["rbi"],
                ) > (top_hitter["hits"], top_hitter["home_runs"], top_hitter["rbi"]):
                    top_hitter = candidate

            innings_pitched = pitching.get("inningsPitched")
            if innings_pitched and float(innings_pitched) > 0:
                candidate = {
                    "name": person_name,
                    "team": team_name,
                    "strikeouts": pitching.get("strikeOuts", 0),
                    "innings_pitched": innings_pitched,
                    "earned_runs": pitching.get("earnedRuns", 0),
                }
                if top_pitcher is None or candidate["strikeouts"] > top_pitcher["strikeouts"]:
                    top_pitcher = candidate

    top_hitter_line = ""
    top_hitter_name = ""
    top_hitter_team = ""
    if top_hitter:
        top_hitter_name = top_hitter["name"]
        top_hitter_team = top_hitter["team"]
        top_hitter_line = (
            f"{top_hitter['hits']}-{top_hitter['at_bats']}, "
            f"{top_hitter['home_runs']} HR, {top_hitter['rbi']} RBI"
        )

    top_pitcher_line = ""
    top_pitcher_name = ""
    top_pitcher_team = ""
    if top_pitcher:
        top_pitcher_name = top_pitcher["name"]
        top_pitcher_team = top_pitcher["team"]
        top_pitcher_line = (
            f"{top_pitcher['innings_pitched']} IP, "
            f"{top_pitcher['strikeouts']} K, {top_pitcher['earned_runs']} ER"
        )

    return {
        "top_hitter": top_hitter_name,
        "top_hitter_team": top_hitter_team,
        "top_hitter_line": top_hitter_line,
        "top_pitcher": top_pitcher_name,
        "top_pitcher_team": top_pitcher_team,
        "top_pitcher_line": top_pitcher_line,
    }


def build_row(session, game):
    home_score = game["home_score"] or 0
    away_score = game["away_score"] or 0

    if home_score > away_score:
        winner, loser, won_by = game["home_team"], game["away_team"], "Home"
    else:
        winner, loser, won_by = game["away_team"], game["home_team"], "Away"
    margin = abs(home_score - away_score)

    row = {
        "game_id": game["game_pk"],
        "date": game["date"],
        "venue": game["venue"],
        "home_team": game["home_team"],
        "away_team": game["away_team"],
        "game_type": game["game_type"],
        "home_score": home_score,
        "away_score": away_score,
        "winner": winner,
        "loser": loser,
        "won_by": won_by,
        "margin": margin,
    }

    try:
        row.update(get_decisions(session, game["game_pk"]))
    except requests.RequestException as e:
        print(f"  [warn] could not fetch decisions for game {game['game_pk']}: {e}")
        row.update({"winning_pitcher": "", "losing_pitcher": "", "save_pitcher": ""})

    try:
        row.update(get_top_performers(session, game["game_pk"], game["home_team"], game["away_team"]))
    except requests.RequestException as e:
        print(f"  [warn] could not fetch boxscore for game {game['game_pk']}: {e}")
        row.update(
            {
                "top_hitter": "",
                "top_hitter_team": "",
                "top_hitter_line": "",
                "top_pitcher": "",
                "top_pitcher_team": "",
                "top_pitcher_line": "",
            }
        )

    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start-date",
        default="2026-03-25",
        help="First date to pull (YYYY-MM-DD). Default: 2026 season opener.",
    )
    parser.add_argument(
        "--end-date",
        default=date.today().isoformat(),
        help="Last date to pull (YYYY-MM-DD). Default: today.",
    )
    parser.add_argument(
        "--output",
        default="mlb_current_season.csv",
        help="Output CSV path. Default: mlb_current_season.csv",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=16,
        help="Number of games to fetch concurrently. Default: 16. "
             "Push higher (e.g. 32) for a faster pull, or lower if you see errors.",
    )
    args = parser.parse_args()

    session = make_session(pool_size=args.workers)

    print(f"Fetching schedule from {args.start_date} to {args.end_date} ...")
    games = get_schedule(session, args.start_date, args.end_date)
    total = len(games)
    print(f"Found {total} completed games. Fetching details with {args.workers} workers ...")

    start_time = time.time()
    rows_by_pk = {}
    done = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(build_row, session, game): game["game_pk"] for game in games}
        for future in as_completed(futures):
            game_pk = futures[future]
            rows_by_pk[game_pk] = future.result()
            done += 1
            if done % 25 == 0 or done == total:
                elapsed = time.time() - start_time
                print(f"  {done}/{total} games done ({elapsed:.1f}s elapsed)")

    # Preserve chronological order in the output file
    rows = [rows_by_pk[g["game_pk"]] for g in games]

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    elapsed = time.time() - start_time
    print(f"\nSaved {len(rows)} rows to {args.output} in {elapsed:.1f}s")


if __name__ == "__main__":
    main()