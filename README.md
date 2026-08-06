# MLB Season Analysis (2026, ongoing)

Exploratory data analysis on the current MLB season, pulled fresh from MLB's own Stats API and analyzed in a Jupyter notebook with pandas, seaborn, and plotly.

This is a follow-up to my IPL project, scaled up: live data instead of a static file, feature engineering, time series trends, and a statistical pass at the end instead of just summary stats.

## Data

`mlb_current_season.csv` — one row per completed game, pulled with `fetch_mlb_data.py` (included in this repo), which hits MLB's free public Stats API. No API key required.

Started at 1,680 rows. 7 had null values across most columns because those games hadn't been played yet at the time of the pull (future scheduled games with no result). Dropped those, leaving 1,673 completed games. `save_pitcher` has expected nulls since most games don't have a save situation.

Columns include date, venue, home/away teams, scores, winner/loser, margin, winning/losing/save pitcher, and top hitter/pitcher for that game.

## What the notebook covers

- Cleaning and type conversion (date parsing, dropping unplayed games)
- Team performance: most wins/losses, best and worst home and away records, home field advantage
- Scoring: total runs by team, runs allowed, average margin of victory, highest/lowest scoring games
- Feature engineering: month/day/weekday, close game and blowout flags, run differential, shutouts, weekend flag
- Time series: games and runs scored by month, home win % by month, average margin by month
- Team comparisons: closest games, most dominant wins, offense vs defense heatmap
- Player analysis: most "top hitter"/"top pitcher" awards, most wins and saves by pitcher
- Venue analysis: highest scoring venues, biggest home field advantage by venue
- Statistical analysis: correlation between home and away scores, distribution of margins, outliers by game type

## A few results

- Home teams have won 51.9% of games this season
- Correlation between home score and away score in the same game: -0.008, essentially no relationship
- Washington Nationals lead the league in total runs scored and have the best average winning margin, but also allow the third-most runs against them
- LA Dodgers have the best road record (37 away wins); the Angels have the worst (18)
- June is the highest-scoring month so far, 9.36 runs/game average
- Weekday games are averaging slightly more total runs than weekend games (9.02 vs 8.85)
- Average total runs per game: 8.96, median 8.0

## Tools

- pandas, numpy for data handling
- seaborn, matplotlib for static plots
- plotly for the interactive treemap and leaderboard charts
- requests for pulling data from the MLB Stats API

## Running it

```bash
pip install pandas numpy seaborn matplotlib plotly requests

# pull the latest completed games
python fetch_mlb_data.py

# then open the notebook
jupyter notebook eda_final.ipynb
```

Re-running `fetch_mlb_data.py` later in the season just adds newly completed games, so the notebook can be re-run against fresh data at any point.

## Notes

Since this is an ongoing season, the numbers above are a snapshot as of the last data pull, not a final-season result.
The script to fetch the data from mlb was made using claude not me.
