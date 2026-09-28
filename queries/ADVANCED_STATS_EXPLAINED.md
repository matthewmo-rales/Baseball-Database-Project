# Advanced stats explained

Plain-language definitions of the metrics used in [analysis.sql](analysis.sql), following the FanGraphs Sabermetrics Library. For each stat: what it measures, why it is preferred over the simpler stat it replaces, and one example from `database/baseball.db` with the query that produced it.

Examples cite a query from analysis.sql (Q01–Q20) where one covers the stat. ERA-, WHIP and some comparison rows are not in any Q-query; those come from short supporting queries S1–S3, listed with their SQL at the end of this file.

## How these stats are stored

| Stat | In the database | Why |
| --- | --- | --- |
| WAR, wOBA, wRC+, FIP, ERA- | Stored as loaded from FanGraphs | They depend on league-wide and park context, not only on the player's own row, so they cannot be computed from the row. |
| ERA, WHIP, K/9 | Generated columns on `pitching_stats` | Computed from `earned_runs`, `hits_allowed`, `walks`, `strikeouts` and `outs_recorded` in the same row. |
| ERA+ (`era_plus`) | Generated column, `10000 / era_minus` | The reciprocal of FanGraphs' ERA-. See the ERA- / ERA+ section. |

Innings are stored as `outs_recorded`. Every per-inning rate here divides by `outs_recorded / 3`, never by the "212.1" display notation, which is base 3.

## WAR (Wins Above Replacement)

**Definition.** An estimate of how many wins a player added compared with a replacement-level player, meaning a freely available minor-leaguer or bench player. For position players, FanGraphs adds batting runs, baserunning runs, fielding runs, a positional adjustment, a league adjustment and replacement-level runs, then converts runs to wins. FanGraphs pitcher WAR is based on FIP (see below), not on runs allowed. The runs-per-win conversion changes by season with the run environment. Replacement level is set so that a replacement-level team would play about .294 ball, the same baseline Q03 and Q11 use.

**Why it is preferred.** Simpler measures (home runs, RBI, batting average, wins for pitchers) each capture one part of a player's contribution and are not on a common scale. WAR puts hitting, running, defense and position on one scale in wins, so a shortstop and a first baseman, or a hitter and a pitcher, can be compared directly.

**Example.** Mookie Betts' WAR by season, 2015–2025: 4.8, 7.4, 4.6, 10.2, 5.8, 2.7, 3.9, 6.0, 7.6, 4.3, 3.4, each within 0.3 of FanGraphs' published figures (Q05). At team level, adding team WAR to a replacement-level baseline lands within 5 wins of actual wins for 217 of 329 team-seasons (66%) and within 10 for 309 (94%) (Q11).

**In this database.** Batting WAR and pitching WAR are in separate tables. A two-way player's total needs both, which is why Q05, Q06, Q09, Q10 and Q15 combine them with `UNION ALL`.

## wOBA (weighted On-Base Average)

**Definition.** A rate stat that credits each way of reaching base by its average run value: unintentional walks, hit-by-pitches, singles, doubles, triples and home runs each get their own weight. The weighted sum is divided by plate appearances (at-bats + walks − intentional walks + sacrifice flies + hit-by-pitches). The weights are recalculated every season from that season's run environment, and the scale is set so league-average wOBA is close to league-average OBP.

**Why it is preferred.** Batting average ignores walks and counts a home run the same as a single. OBP counts walks but treats every time on base equally. SLG weights hits by bases, which does not match their run value (a double is not worth twice a single). wOBA weights each outcome by how many runs it is actually worth.

**Example.** In 2022, among qualified hitters, Jeff McNeil led in batting average (.326) but ranked 17th in wOBA (.365). Aaron Judge ranked 5th in average (.311) and 1st in wOBA (.458) (S1; Judge's wOBA also in Q01).

## wRC+ (weighted Runs Created Plus)

**Definition.** A hitter's runs created per plate appearance, derived from wOBA, then adjusted for park and league and scaled so that 100 is league average. Each point is one percent: 150 means 50% more runs created than an average hitter, 80 means 20% fewer.

**Why it is preferred.** Raw offensive stats depend on the home park and the season's scoring level. wRC+ removes both, so hitters can be compared across parks and seasons. Because it is a rate, it also needs no scaling for the 60-game 2020 season.

**Example.** Aaron Judge's 2022 wRC+ was 206, i.e. about 106% more runs created than a league-average hitter (Q01). Juan Soto's 2020 wRC+ was 202 in 196 plate appearances (S2); the 60-game season does not change how that number reads. This is why Q13 and Q16 measure change in wRC+ across seasons.

## ERA- and ERA+

**Definition.** Both compare a pitcher's ERA to league average after adjusting for park, with 100 as average.

- **ERA-** (FanGraphs): lower is better. 80 means an ERA 20% below league average.
- **ERA+** (Baseball-Reference's scale): higher is better. 120 means 20% better than average.

The database stores FanGraphs' ERA- and derives ERA+ from it. The generated column in `design/schema.sql` is:

```sql
era_plus = CASE WHEN era_minus > 0 THEN ROUND(10000.0 / era_minus, 0) END
```

Our ERA+ will be close to Baseball-Reference's published ERA+ but not identical, because the two sites use different park factors and league baselines.

**Why they are preferred.** ERA depends on how much scoring there is in the league that season and on the home park. The same ERA can be excellent in a high-scoring year and ordinary in a low-scoring one. ERA- and ERA+ put every season and park on the same scale.

**Example.** Clayton Kershaw's ERA was nearly the same in 2015 (2.13) and 2020 (2.16), but his ERA- was 57 in 2015 and 49 in 2020 (`era_plus` 176 and 202). Relative to his league and park, the 2020 figure was the stronger one (S3).

## FIP (Fielding Independent Pitching)

**Definition.** An estimate of a pitcher's ERA using only the outcomes a pitcher controls most directly: home runs, walks plus hit-by-pitches, and strikeouts. The FanGraphs formula is (13 × HR + 3 × (BB + HBP) − 2 × K) / IP, plus a constant. The constant is set each season so that league-average FIP equals league-average ERA, so FIP reads on the ERA scale.

**Why it is preferred.** ERA includes the results of balls in play, which depend heavily on the defense behind the pitcher and on sequencing and chance. Those parts vary a lot from year to year for the same pitcher. By leaving them out, FIP is more stable and tends to be a better guide to future ERA than ERA itself.

**Example.** For pitchers with 100+ IP in consecutive seasons (2020 excluded), FIP predicted next-season ERA with lower mean absolute error than ERA in every bucket. Where ERA was well below FIP, FIP's error was 0.83 vs ERA's 1.16 (n=60). Where ERA was well above FIP, 0.77 vs 1.06 (n=55) (Q19). For a single season: Gerrit Cole in 2019 had a 2.50 ERA and 2.64 FIP (S3).

## WHIP (Walks plus Hits per Inning Pitched)

**Definition.** (Walks + hits allowed) / innings pitched: the average number of baserunners a pitcher allows per inning through hits and walks. Hit-by-pitches and errors are not counted.

**Why it is used.** WHIP is itself a simple stat, not an advanced one. Compared with ERA, it does not depend on the order in which baserunners were allowed or on the official scorer's earned/unearned run decisions. Its limits: it counts a walk the same as a home run, and like ERA it includes hits on balls in play, which depend on the defense. It is included here because it is widely reported and easy to read.

**Example.** Gerrit Cole's 2019 WHIP was 0.89 and Clayton Kershaw's 2015 WHIP was 0.88, both under one baserunner per inning (S3).

## K/9 (Strikeouts per Nine Innings)

**Definition.** Strikeouts × 9 / innings pitched. In this database: `strikeouts * 27 / outs_recorded`.

**Why it is used, and its limit.** K/9 puts strikeout totals on a rate basis, so pitchers with different workloads can be compared (Q04 uses it alongside raw strikeouts). FanGraphs recommends K% (strikeouts / batters faced) over K/9: a pitcher who allows more baserunners faces more batters per inning and so has more chances to strike someone out, which inflates K/9. K% divides by batters faced and avoids that.

**Example.** Gerrit Cole led MLB with 326 strikeouts in 2019, a 13.82 K/9 (Q04). As a K%, that is 326 strikeouts in 817 batters faced, 39.9% (S3).

## Supporting queries

These ran on the read-only connection used for VERIFY.md (`file:database/baseball.db?mode=ro`, SQLite 3.50.4). They are not part of analysis.sql.

### S1: Batting average rank vs wOBA rank, 2022 qualified hitters

```sql
WITH q AS (
  SELECT b.season_year, p.player_id, p.full_name, b.batting_avg,
         ROUND(b.woba, 3) AS woba, b.wrc_plus,
         RANK() OVER (PARTITION BY b.season_year ORDER BY b.batting_avg DESC) AS avg_rank,
         RANK() OVER (PARTITION BY b.season_year ORDER BY b.woba DESC)        AS woba_rank
  FROM v_batting_season AS b
  JOIN players          AS p ON p.player_id   = b.player_id
  JOIN seasons          AS s ON s.season_year = b.season_year
  WHERE b.plate_appearances >= 3.1 * s.scheduled_games
)
SELECT * FROM q
WHERE season_year = 2022 AND (avg_rank <= 3 OR woba_rank <= 3)
ORDER BY avg_rank;
```

| player_id | full_name | batting_avg | woba | wrc_plus | avg_rank | woba_rank |
| --- | --- | --- | --- | --- | --- | --- |
| 15362 | Jeff McNeil | .326 | .365 | 140 | 1 | 17 |
| 5361 | Freddie Freeman | .325 | .393 | 157 | 2 | 5 |
| 9218 | Paul Goldschmidt | .317 | .419 | 175 | 3 | 3 |
| 15640 | Aaron Judge | .311 | .458 | 206 | 5 | 1 |
| 19556 | Yordan Alvarez | .306 | .427 | 185 | 7 | 2 |

### S2: Hitter example rows

```sql
SELECT p.player_id, p.full_name, b.season_year, b.plate_appearances,
       b.batting_avg, b.obp, b.slg, ROUND(b.woba, 3) AS woba, b.wrc_plus
FROM v_batting_season AS b
JOIN players          AS p ON p.player_id = b.player_id
WHERE (b.player_id = 15640 AND b.season_year = 2022)   -- Aaron Judge
   OR (b.player_id = 20123 AND b.season_year = 2020);  -- Juan Soto
```

| player_id | full_name | season_year | PA | AVG | OBP | SLG | wOBA | wRC+ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 15640 | Aaron Judge | 2022 | 696 | .311 | .425 | .686 | .458 | 206 |
| 20123 | Juan Soto | 2020 | 196 | .351 | .490 | .695 | .478 | 202 |

### S3: Pitcher example rows

```sql
SELECT p.player_id, p.full_name, ps.season_year, ps.innings_pitched,
       ps.era, ROUND(ps.era_minus) AS era_minus, ps.era_plus,
       ROUND(ps.fip, 2) AS fip, ps.whip, ps.k_per_9,
       ps.strikeouts, ps.batters_faced,
       ROUND(100.0 * ps.strikeouts / ps.batters_faced, 1) AS k_pct
FROM pitching_stats AS ps
JOIN players        AS p ON p.player_id = ps.player_id
WHERE (ps.player_id = 13125 AND ps.season_year = 2019)          -- Gerrit Cole
   OR (ps.player_id = 2036  AND ps.season_year IN (2015, 2020)); -- Clayton Kershaw
```

| player_id | full_name | season_year | IP | ERA | ERA- | era_plus | FIP | WHIP | K/9 | K | BF | K% |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 13125 | Gerrit Cole | 2019 | 212.33 | 2.50 | 55 | 180 | 2.64 | 0.89 | 13.82 | 326 | 817 | 39.9 |
| 2036 | Clayton Kershaw | 2015 | 232.67 | 2.13 | 57 | 176 | 1.99 | 0.88 | 11.64 | 301 | 890 | 33.8 |
| 2036 | Clayton Kershaw | 2020 | 58.33 | 2.16 | 49 | 202 | 3.31 | 0.84 | 9.57 | 62 | 221 | 28.1 |
