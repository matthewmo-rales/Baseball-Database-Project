# Analytics queries (Q01–Q20)

Twenty analytical queries against `database/baseball.db` (FanGraphs season aggregates, 2015–2025). All SQL is in [analysis.sql](analysis.sql). Row counts, sample output and the fact checks behind each result are in [VERIFY.md](VERIFY.md). Q12 has two parts (Q12a, Q12b), so there are 21 query blocks. All 21 run without error on SQLite 3.50.4.

Every number below comes from VERIFY.md or from the query it names. Definitions of the advanced stats used here are in [ADVANCED_STATS_EXPLAINED.md](ADVANCED_STATS_EXPLAINED.md).

## Conventions used by every query

- Hitter queries read `v_batting_season` (9,173 rows), not `batting_stats` (15,521). The view drops the 6,348 rows with 0 plate appearances. (Row counts from `SELECT COUNT(*)` on each.)
- A player traded mid-season has one combined row with `team_id IS NULL` and `is_multi_team = 1`. Queries that group by team exclude these rows and say so.
- 2020 was a 60-game season. Qualification thresholds scale by `scheduled_games`. Counting stats compared across seasons scale by `162 / scheduled_games`. Queries that are sensitive to single-season noise (Q06, Q15, Q17, Q19) exclude 2020.
- Position queries use only the unambiguous positions C, 1B, 2B, 3B, SS, OF (1,362 players, by `SELECT COUNT(*) FROM players` with that filter). DH is excluded because only 1–5 players a season carry it.
- Qualified hitters: `PA >= 3.1 * scheduled_games`. Qualified pitchers: `outs_recorded >= 3 * scheduled_games`. Some queries use their own minimums, listed under each query.
- The data covers 2015–2025 only. Career totals, streaks and cohort figures are truncated at both ends of that window.

## Tier 1: JOINs and aggregation

### Q01: Top 10 hitters by wOBA each season (qualified)

- **Business question:** Who were the best overall hitters each year, using a measure that credits each type of hit by its run value instead of batting average?
- **Technique:** `RANK()` partitioned by season in a CTE (SQLite has no `QUALIFY`); four-table join; `LEFT JOIN` to `teams` so multi-team players stay in.
- **Key finding:** 2022 leader is Aaron Judge (NYY), .458 wOBA, 206 wRC+. 2025 leader is Judge again, .463 wOBA. 110 rows, 10 per season, no ties. (Q01)
- **Main caveat:** The qualification threshold scales with `scheduled_games`, so 2020 requires 186 PA (3.1 × 60) instead of 502.2 (3.1 × 162).

### Q02: Top 5 WAR per position per season

- **Business question:** Who were the most valuable players at each position?
- **Technique:** `RANK()` partitioned by two columns (position, season).
- **Key finding:** 2019 top catcher is J.T. Realmuto, 5.9 WAR. 330 rows across 6 positions and 11 seasons. (Q02)
- **Main caveat:** `primary_position` is a career-level label, not a per-season one. Unambiguous positions only; DH, IF, P and NULL are excluded.

### Q03: Team payroll efficiency

- **Business question:** Which teams turned payroll into wins most efficiently, compared with other teams in the same season?
- **Technique:** Window `AVG()` over the season partition for league-average payroll, mixed with row-level math; `RANK()` within season. "Marginal wins" are wins above a .294 replacement-level team, per $10M of payroll.
- **Key finding:** Tampa Bay ranks 1st in 2019, 2020 and 2021, and in the top 3 in 7 of 11 seasons. 2025 leader is Milwaukee, 3.52 marginal wins per $10M on a $140.3M payroll (0.70 of league average). (Q03)
- **Main caveat:** Payroll inflates every year, so comparisons are within a season. The source reports 2020 payroll prorated (2020 maximum $128.1M), so 2020 figures are not comparable to other seasons.

### Q04: Pitcher strikeout leaders

- **Business question:** Who were the top strikeout pitchers each season?
- **Technique:** Join plus `RANK()`; innings come from `outs_recorded`, never the base-3 display notation.
- **Key finding:** 2019 leader is Gerrit Cole, 326 K, 13.82 K/9. 114 rows (ties at #10 are kept). (Q04)
- **Main caveat:** Minimum 50 IP (150 outs), scaled for 2020.

## Tier 2: Window functions

### Q05: Career WAR trajectory with 3-year rolling average

- **Business question:** Is a given player trending up, at his peak, or declining?
- **Technique:** `UNION ALL` of batting and pitching WAR so two-way players are complete; `AVG() OVER (ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)`; `LAG()`.
- **Key finding:** Example target Mookie Betts: stored WAR 2015–2025 is 4.8, 7.4, 4.6, 10.2, 5.8, 2.7, 3.9, 6.0, 7.6, 4.3, 3.4, each within 0.3 of FanGraphs. (Q05)
- **Main caveat:** The rolling frame counts rows, not years, so a skipped season still sits "adjacent". Seasons before 2015 are missing. The target is a `player_id`, because 19 full names are shared by two players each.

### Q06: Biggest year-over-year WAR risers and fallers

- **Business question:** Who broke out or collapsed from one season to the next?
- **Technique:** `LAG()` plus a check that the previous row is the previous year; two `ROW_NUMBER()`s (ascending and descending) pull both tails in one pass.
- **Key finding:** Largest rise is Aaron Judge 2016→2017, +8.7 WAR. Other checked rows: Bryce Harper 2015→2016, −7.4; Ronald Acuña Jr. 2023→2024, −8.2. (Q06)
- **Main caveat:** 2020 is excluded, so 2019→2021 is not treated as consecutive. There is no playing-time minimum, on purpose, so returns from injury appear as risers.

### Q07: WAR percentile among position-mates

- **Business question:** How does a player rank against others at his position in the same season, rather than the whole league?
- **Technique:** `PERCENT_RANK()` and `COUNT(*) OVER` the same partition (position, season); outer filter on partition size.
- **Key finding:** All 66 of Q02's rank-1 players sit at the 100th percentile. Smallest position-season group is 16 players. (Q07)
- **Main caveat:** Minimum 300 PA (scaled for 2020). Groups with fewer than 10 eligible players are dropped; none are today.

### Q08: Milestone tracking with cumulative totals

- **Business question:** Which players reached 1,000 hits within 2015–2025, and in which season?
- **Technique:** Running `SUM() OVER` a named `WINDOW` with `ROWS UNBOUNDED PRECEDING`.
- **Key finding:** 72 players cross 1,000 hits in the window. Freddie Freeman crosses in 2021 (1,048). (Q08)
- **Main caveat:** Counts hits from 2015 onward only, not true career totals.

### Q09: Consecutive seasons of 3+ WAR

- **Business question:** Who is consistently good, as opposed to good for one year?
- **Technique:** Gaps-and-islands: `season_year - ROW_NUMBER()` is constant across an unbroken run, so it works as a group key.
- **Key finding:** 116 streaks of 3+ seasons. Longest are 11 seasons (2015–2025): Mookie Betts (60.7 WAR) and Francisco Lindor (60.2). Mike Trout's streak is 2015–2020, 6 seasons, 44.1 WAR. (Q09)
- **Main caveat:** 2020 WAR is scaled to 162 games so the short season doesn't break streaks. A streak starting in 2015 may have begun earlier.

## Tier 3: Multi-join business logic

### Q10: Birth-cohort productivity

- **Business question:** Which birth years produced the most MLB value in 2015–2025, and how much of that is timing?
- **Technique:** `UNION ALL` of batting and pitching WAR, per-player career CTE, cohort `GROUP BY` with conditional aggregation (`CASE` inside `SUM`).
- **Key finding:** Top three cohorts are 1992 (904.9 WAR), 1991 (860.3) and 1990 (856.1). Their ages during the window are 23–33, 24–34 and 25–35, so they were at peak age for the whole window. (Q10)
- **Main caveat:** Window truncation drives this result. Older cohorts are missing their early careers and younger cohorts their late careers. This is a birth cohort, not a draft class.

### Q11: Team cost per WAR

- **Business question:** How many payroll dollars did each team spend per win of player value, and does roster WAR explain actual wins?
- **Technique:** `UNION ALL` of single-team batting and pitching WAR, aggregated to team-season, joined to payroll, `RANK()` within season.
- **Key finding:** 2025 lowest cost is Milwaukee at $3.08M per WAR. As a sanity check, implied wins (replacement level plus team WAR) are within 5 of actual wins for 217 of 329 team-seasons (66%) and within 10 for 309 (94%). Implied wins average 1.9 below actual. (Q11)
- **Main caveat:** Multi-team player-seasons are excluded, so team WAR is understated for teams that trade a lot. That likely explains the 1.9-win shortfall. One team-season (2025 COL) has team WAR ≤ 0 and is dropped.

### Q12a: Pythagorean over- and under-performers

- **Business question:** Which teams won far more or fewer games than their run differential predicts?
- **Technique:** Expected win% = RS² / (RS² + RA²), computed inline; ranked by luck per 162 games.
- **Key finding:** Largest overperformer is 2021 Seattle, +14.7 wins. 2020 Miami ranks 2nd at +14.4 per 162 (+5.3 actual wins in 60 games). 2016 Texas ranks 4th, +13.1. (Q12a)
- **Main caveat:** Uses actual games played (W + L), not 162. Win% and pythag are computed inline because the generated columns are rounded to 3 decimals.

### Q12b: Does Pythagorean luck persist into the next season?

- **Business question:** Should a team that beat or missed its run differential expect to do so again?
- **Technique:** `LEAD()` pairs each team-season with the next; results bucketed by the first season's luck.
- **Key finding:** Lucky teams (+6.7 wins/162, n=50) and neutral teams (n=191) both average +0.2 the next season, i.e. no persistence. Unlucky teams (−6.5, n=59) average −1.5 the next season (SE 0.46, about 3.3 SE from zero). The expected result was near zero for all three buckets; this one did not match. (Q12b)
- **Main caveat:** Causes are not tested here. Three buckets were compared, so a single ~3 SE result should be read with that in mind. Assumes `team_id` is stable across relocations.

### Q13: Does changing teams change a hitter?

- **Business question:** Do hitters who switch teams between seasons improve or decline more than similar hitters who stay?
- **Technique:** Self-join on (player, season, season + 1); team-change flag; grouped by prior-season wRC+ tier so movers are compared with stayers of similar quality (the regression-to-the-mean control).
- **Key finding:** Both groups regress toward average. In the 120+ tier, movers drop 19.4 wRC+ (n=60) and stayers 16.6 (n=495). In the 100–119 tier, movers drop 6.7 (n=80) and stayers 1.7 (n=483). Below 100, both groups rise: 80–99 movers +8.6 (n=81), stayers +7.1 (n=368). (Q13)
- **Main caveat:** Single-team seasons only; pre- and post-trade splits within a season are impossible because a traded player has one combined row. Movers are not random, since teams choose whom to acquire.

### Q14: Position value trend over the decade

- **Business question:** Where is hitting talent deep or thin by position?
- **Technique:** Aggregate CTE of PA-weighted WAR per 600 PA, then windows over the aggregates (position decade average, `LAG()` for year-over-year change).
- **Key finding:** Decade means of WAR per 600 PA: SS 2.60, 3B 2.52, 2B 1.96, OF 1.92, C 1.83, 1B 1.61. (Q14)
- **Main caveat:** WAR already includes a positional adjustment designed to equalize positions, so the spread reflects where talent was concentrated in this window, not the value of the position itself. No payroll by position exists.

## Tier 4: CTEs and predictive setup

### Q15: Breakout seasons

- **Business question:** Which seasons stood far above a player's usual level?
- **Technique:** Leave-one-out average, (career sum − this season) / (n − 1), from window `SUM` and `COUNT`, so the breakout season doesn't raise its own baseline.
- **Key finding:** Top entry is Chris Davis 2015, 5.4 WAR against −0.7 in his other seasons (+6.1). The top 25 include award seasons: Harper 2015 (MVP), Arrieta 2015 (Cy Young), deGrom 2018 (Cy Young), Bellinger 2019 (MVP), Acuña 2023 (MVP). (Q15)
- **Main caveat:** Descriptive, not predictive: the baseline includes later seasons. 2020 excluded. Minimum 3 seasons.

### Q16: Hitter aging curves by position group (delta method)

- **Business question:** At what age do hitters peak and begin to decline, and does it differ by position?
- **Technique:** Age on June 30; self-join on consecutive seasons; year-to-year wRC+ change weighted by the harmonic mean of PA; running `SUM` builds the curve; 3-age moving average for smoothing; a naive average-by-age column shows survivorship bias.
- **Key finding:** Middle infielders peak at 27 (smoothed curve +5.7) and corner infielders at 26 (+4.6). Catchers and outfielders show no improvement after their first qualifying age (C 25, OF 23), likely a selection effect, so no peak age is claimed for them. The naive column stays flat at older ages while the delta curves fall: for OF, the naive average is 99.7 wRC+ at 23 and 104.8 at 35, but the smoothed delta curve is at −42.3 by 35. That gap is the survivorship contrast: only hitters good enough to keep playing appear in the naive average at older ages. (Q16)
- **Main caveat:** Offense only. The first season of each pair needs 200+ PA, so it skews toward good seasons. Cells with fewer than 15 pairs are dropped.

### Q17: Performance consistency (WAR variance)

- **Business question:** Among good hitters, who is reliable and who is volatile?
- **Technique:** Sample variance without `STDDEV`: (AVG(x²) − AVG(x)²) · n / (n − 1); `sqrt()` for standard deviation.
- **Key finding:** Most consistent is Kyle Tucker: 5 seasons, mean 4.69 WAR, SD 0.31. (Q17)
- **Main caveat:** Hitters only, 300+ PA seasons, 2020 excluded, minimum 5 seasons, mean WAR ≥ 2.5. `player_id` is shown because names repeat.

### Q18: Comparable-player finder

- **Business question:** Which hitter-seasons have the offensive profile most similar to a target?
- **Technique:** K%, BB% and ISO made relative to each season's average; standardized squared Euclidean distance over K%, BB%, ISO and wRC+; `CROSS JOIN` to the target row.
- **Key finding:** For Freddie Freeman 2023 (K 16.6%, BB 9.9%, ISO .235, 161 wRC+), the five nearest are Altuve 2022, Guerrero Jr. 2024, Cabrera 2016, Tucker 2021 and Alvarez 2024. (Q18)
- **Main caveat:** Offense only; no defense or speed. Comps can come from any season 2015–2025. Target is keyed on `player_id`.

### Q19: ERA minus FIP as a regression signal

- **Business question:** When a pitcher's ERA is far from his FIP, does next season's ERA move toward FIP?
- **Technique:** Self-join on consecutive seasons; bucket by the ERA−FIP gap; compare mean absolute error of ERA and FIP as predictors of next-season ERA.
- **Key finding:** FIP predicts next ERA better in every bucket. The difference is largest where the gap is large: ERA well below FIP, 0.83 vs 1.16 MAE (n=60); ERA well above FIP, 0.77 vs 1.06 (n=55). (Q19)
- **Main caveat:** Minimum 100 IP in both seasons; 2020 excluded.

## Additional

### Q20: Top 10 home run hitters by season

- **Business question:** Who led in power each year?
- **Technique:** `RANK()` partitioned by season in a CTE.
- **Key finding:** 2017 leader is Giancarlo Stanton, 59 HR. 2025 leader is Cal Raleigh, 60 HR. 121 rows; the 11 beyond 110 are ties at #10. (Q20)
- **Main caveat:** Raw counts, not scaled for 2020.

## Scope changes

The original project brief proposed several queries the data cannot support. Each was replaced with the closest question the data can answer.

| Original idea | Why it was dropped | Replacement |
| --- | --- | --- |
| Undervalued players by salary; contract value (WAR per $) | The data has team payroll only, no individual salaries. | **Q11**: team payroll dollars per team WAR. Value is measured at the team level. |
| Injury recovery | No injured-list data and no game logs. | **Q16**: aging curves by position group, using the delta method. Q06 (year-over-year risers, no playing-time minimum) is the closest proxy for returns from injury. |
| Mid-season trade impact (pre/post) | A player traded mid-season has one combined season row, so pre- and post-trade splits do not exist. | **Q13**: hitters who changed teams between seasons, compared with hitters of similar quality who stayed. |
| Best draft class | No draft data. | **Q10**: birth cohort, with the ages each cohort covers in the window shown next to the result. |
| Position scarcity with payroll | No payroll by position. | **Q14**: WAR per 600 PA by position, WAR only. |

## How to run the queries

Build the database first if it isn't there; see [database/README.md](../database/README.md). Q03 and Q11 need the optional payroll file.

### DB Browser for SQLite

1. Open `database/baseball.db` (File > Open Database Read Only avoids accidental edits).
2. Open `queries/analysis.sql` in the Execute SQL tab.
3. Highlight one query (from its `-- Q##:` header to its closing semicolon) and press Ctrl+Return. With a selection, DB Browser runs only the selected text. With nothing selected it runs the whole file and shows only the last result.

Q05 and Q18 take a target in a `params` CTE at the top of the query: a `player_id` for Q05, a `player_id` and season for Q18. Edit the values there. To look up a `player_id`:

```sql
SELECT player_id, full_name, birth_date FROM players WHERE full_name LIKE '%Freeman%';
```

### Python

Use the project venv. This splits `analysis.sql` on its `-- Q##:` headers and runs queries on a read-only connection:

```python
import re
import sqlite3
from pathlib import Path

sql = Path("queries/analysis.sql").read_text(encoding="utf-8")

# Each query starts with a header line like "-- Q01:" or "-- Q19 (optional):".
blocks = re.split(r"(?m)^(?=-- Q\d+[a-z]?(?: \([^)]*\))?:)", sql)[1:]
queries = {re.match(r"-- (Q\d+[a-z]?)", b).group(1): b for b in blocks}

con = sqlite3.connect("file:database/baseball.db?mode=ro", uri=True)
con.execute("PRAGMA foreign_keys = ON")

cur = con.execute(queries["Q01"])
print([d[0] for d in cur.description])
for row in cur.fetchmany(5):
    print(row)
```

Run it from the repo root. Tested against the current database: it finds all 21 blocks and each returns the row count listed in VERIFY.md.

Q17 uses `sqrt()`, which requires SQLite built with math functions. Python's bundled SQLite 3.50.4 here has it; if `SELECT sqrt(4);` fails on another build, drop the `sd_war` column (the ranking uses `var_war` and is unchanged).
