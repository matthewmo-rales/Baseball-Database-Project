# Phase 3 query verification

Verification log for `queries/analysis.sql` (Q01–Q20, with Q12 split into Q12a/Q12b = 21 blocks) against `database/baseball.db`. Regenerated after the final review (Q20 ties, Q14 wording, Q16 finding, human checks for Q05/Q06/Q17/Q18); Q01 RANK change added afterwards.

Summary: **21 of 21 blocks run without error.** Verdicts: PASS 20, FINDING 1. FINDING = the original expectation failed and the header now records the actual result. Q16 is PASS, recorded as a finding in its header.

## 1. Environment

| Check | Result |
|---|---|
| SQLite version (Python `sqlite3.sqlite_version`) | 3.50.4 |
| `SELECT sqrt(4);` | works → `2.0` (used by Q17 `sd_war`) |
| `WINDOW w AS (...)` clause | works (used by Q08) |
| Runner | Python sqlite3, `file:database/baseball.db?mode=ro`, `PRAGMA foreign_keys = ON`; each block split on its `-- Q##:` header and run separately |

## 2. Assumed → actual names (applied in the first pass)

| Table | Assumed | Actual |
|---|---|---|
| players | `name` | `full_name` |
| teams | `abbreviation` | `fangraphs_abbrev` |
| team_stats | `runs_for` / `runs_against` | `runs_scored` / `runs_allowed` |
| team_stats | `payroll` | `payroll_usd` |
| batting_stats / v_batting_season | `rbis` | `rbi` |

## 3. Generated-column swaps

| Query | Swap | Output change |
|---|---|---|
| Q03 | win% → `team_stats.win_pct` | none |
| Q04 | IP → `innings_pitched`, K/9 → `k_per_9` | none |
| Q19 | ERA → `pitching_stats.era` | two averaged cells ±0.01; bucket counts unchanged |
| Q12a/b | **kept inline** (decision 3) | generated win%/pythag are 3-dp rounded; luck × games would shift up to ~0.16 wins and move 3 team-seasons between Q12b buckets |

Pythag exponent in the generated column: **2**.

## 4. Changes applied from review

| # | Change | Where |
|---|---|---|
| 1 | DH excluded from the position set (matches the 1,362 unambiguous set). Q16 groups 1B/3B as `CI`; dead LF/CF/RF branch removed | Q02, Q07, Q14, Q16 |
| 2 | `COUNT(*) OVER (PARTITION BY pos, season_year)` in the CTE; keep partitions with ≥ 10 players; `n_in_group` shown | Q07 |
| 3 | `luck_per_162 = (win_pct - pyth) * 162` added; `ORDER BY ABS(luck_per_162)`; win%/pythag stay inline | Q12a |
| 4 | Verified line records the persistence finding | Q12b |
| 5 | Caveat: team-seasons with team WAR ≤ 0 dropped (2025 COL) | Q11 |
| 6 | `smoothed_change` (3-age moving average) and `smoothed_curve` added, raw columns kept; survivorship caveat rewritten; anchor stated | Q16 |
| 7 | `sd_war` enabled; `player_id` in output; min 5 seasons kept | Q17 |
| 8 | Params are `target_player_id` (5361) + `target_season` (2023); id-lookup comment; caveat says cross-season | Q18 |
| 9 | Draft merged as body of `analysis.sql`; HR leaderboard is Q20 with standard header; old Query 2 dropped; `analysis_draft.sql` deleted | analysis.sql |
| 10 | Header comments: pybaseball → direct FanGraphs API loader, 3NF → BCNF (comments only; schema still builds, 9 objects) | design/schema.sql |
| 11 | Conventions documented: position values, DH rule, SQLite/sqrt, rounding of generated columns, 2020 payroll, duplicate names (column names are defined in the schema) | queries/README.md, design/schema.sql |

Also: every `Verified: TODO` line was filled in. Checked facts were marked `PASS`; the five that needed a human check (Q05, Q06, Q16, Q17, Q18) were marked `TODO (human check)` at that point and are now resolved (section 4b).

## 4b. Changes applied in the final review

| # | Change | Where |
|---|---|---|
| 12 | `ROW_NUMBER()` → `RANK()` so ties at #10 are kept; caveat and Verified updated (resolves O1) | Q20 |
| 13 | Verified line reworded: the positional adjustment equalizes positions, so differences reflect talent concentration (SS/3B deepest, 1B thinnest); "matching the adjustment" claim removed; O3 dropped | Q14 |
| 14 | Verified = PASS as a finding: MI/CI peak 26–27; C/OF no improvement after first qualifying age, likely selection; no peak-age claim for C/OF (resolves O2) | Q16 |
| 15 | Human checks recorded as PASS in the owner's wording (resolves O4) | Q05, Q06, Q17, Q18 |
| 16 | `ROW_NUMBER()` → `RANK()` to match Q20; no ties appeared, still 110 rows | Q01 |

## 5. Per-query results

| Query | Rows | Runtime (ms) | Error | Verdict |
|---|---|---|---|---|
| Q01 | 110 | 20.1 | none | PASS |
| Q02 | 330 | 25.0 | none | PASS |
| Q03 | 330 | 4.4 | none | PASS |
| Q04 | 114 | 15.7 | none | PASS |
| Q05 | 11 | 24.8 | none | PASS |
| Q06 | 30 | 60.9 | none | PASS |
| Q07 | 2542 | 26.5 | none | PASS |
| Q08 | 72 | 20.7 | none | PASS |
| Q09 | 116 | 23.4 | none | PASS |
| Q10 | 24 | 32.6 | none | PASS |
| Q11 | 329 | 25.4 | none | PASS |
| Q12a | 20 | 1.0 | none | PASS |
| Q12b | 3 | 0.9 | none | FINDING |
| Q13 | 8 | 15.9 | none | PASS |
| Q14 | 66 | 11.4 | none | PASS |
| Q15 | 25 | 33.8 | none | PASS |
| Q16 | 48 | 43.3 | none | PASS |
| Q17 | 25 | 9.6 | none | PASS |
| Q18 | 5 | 18.0 | none | PASS |
| Q19 | 3 | 6.7 | none | PASS |
| Q20 | 121 | 19.4 | none | PASS |

Runtimes are single runs on this machine.

### Q01: PASS

- Rows: 110 · Runtime: 20.1 ms · Errors: none
- Header says: *PASS. 2022 rank 1 = Aaron Judge (NYY, .458 wOBA, 206 wRC+). RANK re-run: 110 rows, 10 per season, no ties in any season.*
- Check: 2022 #1 = Aaron Judge, NYY, .458 wOBA, 206 wRC+. 2020 threshold scaled (Soto qualifies at 196 PA ≥ 186). Now RANK() instead of ROW_NUMBER(): **no ties appeared**, output unchanged at 110 rows (10 per season). wOBA is stored unrounded (e.g. 0.46116…), so exact ties are rare; 6 pairs look tied at 3 decimals (e.g. 2021 .391, 2020 .413) but are ranked by full value.

| season_year | woba_rank | name | team | pa | woba | wrc_plus |
|---|---|---|---|---|---|---|
| 2025 | 1 | Aaron Judge | NYY | 679 | 0.463 | 203 |
| 2025 | 2 | Shohei Ohtani | LAD | 727 | 0.418 | 172 |
| 2025 | 3 | George Springer | TOR | 586 | 0.408 | 166 |
| 2025 | 4 | Cal Raleigh | SEA | 705 | 0.392 | 161 |
| 2025 | 5 | Kyle Schwarber | PHI | 724 | 0.391 | 150 |

### Q02: PASS

- Rows: 330 · Runtime: 25.0 ms · Errors: none
- Header says: *PASS. 2019 C rank 1 = J.T. Realmuto (5.9 WAR).*
- Check: 2019 C rank 1 = J.T. Realmuto, 5.9 WAR. Now 6 positions (C/1B/2B/3B/SS/OF), 330 rows (was 356 with DH).

| season_year | pos | pos_rank | name | pa | war |
|---|---|---|---|---|---|
| 2025 | 1B | 1 | Matt Olson | 724 | 4.7 |
| 2025 | 1B | 2 | Nick Kurtz | 489 | 4.3 |
| 2025 | 1B | 3 | Vladimir Guerrero Jr. | 680 | 3.9 |
| 2025 | 1B | 4 | Freddie Freeman | 627 | 3.9 |
| 2025 | 1B | 5 | Michael Busch | 592 | 3.5 |

### Q03: PASS

- Rows: 330 · Runtime: 4.4 ms · Errors: none
- Header says: *PASS. TBR ranks 1st in 2019, 2020, 2021 and top 3 in 7 of 11 seasons. Source 2020 payroll is prorated (2020 max $128.1M).*
- Check: TBR is rank 1 in 2019, 2020, 2021 and top 3 in 7 of 11 seasons. 2020 payroll is prorated in the source (2020 max $128.1M vs $248.7M–$401.0M elsewhere).

| season_year | team | wins | losses | win_pct | payroll_millions | payroll_vs_league_avg | marginal_wins_per_10m | efficiency_rank |
|---|---|---|---|---|---|---|---|---|
| 2025 | MIL | 97 | 65 | 0.599 | 140.3 | 0.7 | 3.52 | 1 |
| 2025 | MIA | 79 | 83 | 0.488 | 90.9 | 0.45 | 3.45 | 2 |
| 2025 | CLE | 88 | 74 | 0.543 | 118.4 | 0.59 | 3.41 | 3 |
| 2025 | TBR | 77 | 85 | 0.475 | 102.8 | 0.51 | 2.86 | 4 |
| 2025 | CIN | 83 | 79 | 0.512 | 135.8 | 0.68 | 2.6 | 5 |

### Q04: PASS

- Rows: 114 · Runtime: 15.7 ms · Errors: none
- Header says: *PASS. 2019 rank 1 = Gerrit Cole, 326 K, 13.82 K/9.*
- Check: 2019 #1 = Gerrit Cole, 326 K, 13.82 K/9. `ip` is decimal innings (212.3 = 212⅓), not display notation.

| season_year | k_rank | name | strikeouts | ip | k9 | war |
|---|---|---|---|---|---|---|
| 2025 | 1 | Garrett Crochet | 255 | 205.3 | 11.18 | 5.7 |
| 2025 | 2 | Tarik Skubal | 241 | 195.3 | 11.1 | 6.7 |
| 2025 | 3 | Logan Webb | 224 | 207.0 | 9.74 | 5.5 |
| 2025 | 4 | Paul Skenes | 216 | 187.7 | 10.36 | 6.5 |
| 2025 | 4 | Jesús Luzardo | 216 | 183.7 | 10.58 | 5.4 |

### Q05: PASS

- Rows: 11 · Runtime: 24.8 ms · Errors: none
- Header says: *PASS. Betts 2015-2025 matches FanGraphs within 0.3 every season. Stored WAR 2015–2025: 4.8, 7.4, 4.6, 10.2, 5.8, 2.7, 3.9, 6.0, 7.6, 4.3, 3.4.*
- Check: Human check done: Betts 2015-2025 matches FanGraphs within 0.3 every season.

| player_id | name | season_year | war | war_per_162 | rolling_3yr | change_vs_prev |
|---|---|---|---|---|---|---|
| 13611 | Mookie Betts | 2015 | 4.8 | 4.8 | 4.8 | None |
| 13611 | Mookie Betts | 2016 | 7.4 | 7.4 | 6.1 | 2.6 |
| 13611 | Mookie Betts | 2017 | 4.6 | 4.6 | 5.6 | -2.7 |
| 13611 | Mookie Betts | 2018 | 10.2 | 10.2 | 7.4 | 5.5 |
| 13611 | Mookie Betts | 2019 | 5.8 | 5.8 | 6.9 | -4.4 |

### Q06: PASS

- Rows: 30 · Runtime: 60.9 ms · Errors: none
- Header says: *PASS. Judge, Harper, Acuna rows all match FanGraphs within 0.3 (Judge 2016->17 +8.7, Harper 2015->16 -7.4, Acuna 2023->24 -8.2).*
- Check: Human check done: Judge, Harper, Acuna rows all match FanGraphs within 0.3.

| direction | name | prev_season | season_year | prev_war | war | delta |
|---|---|---|---|---|---|---|
| Riser | Aaron Judge | 2016 | 2017 | -0.0 | 8.7 | 8.7 |
| Riser | Ronald Acuña Jr. | 2022 | 2023 | 2.4 | 9.1 | 6.8 |
| Riser | Aaron Judge | 2023 | 2024 | 4.7 | 11.2 | 6.5 |
| Riser | Jean Segura | 2015 | 2016 | 0.1 | 6.1 | 6.1 |
| Riser | Jurickson Profar | 2023 | 2024 | -1.6 | 4.4 | 6.0 |

### Q07: PASS

- Rows: 2542 · Runtime: 26.5 ms · Errors: none
- Header says: *PASS. All 66 Q02 rank-1 players sit at 100.0. Smallest partition is 16 players, so the >= 10 floor currently drops nothing.*
- Check: All 66 Q02 rank-1 players sit at 100.0 (was 67/76 with DH). 66 position-seasons, smallest has 16 players, so the ≥10 floor drops nothing today; it guards future data. 2542 rows (was 2553).

| season_year | pos | name | pa | war | war_percentile | n_in_group |
|---|---|---|---|---|---|---|
| 2025 | 1B | Matt Olson | 724 | 4.7 | 100.0 | 27 |
| 2025 | 1B | Nick Kurtz | 489 | 4.3 | 96.2 | 27 |
| 2025 | 1B | Vladimir Guerrero Jr. | 680 | 3.9 | 92.3 | 27 |
| 2025 | 1B | Freddie Freeman | 627 | 3.9 | 88.5 | 27 |
| 2025 | 1B | Michael Busch | 592 | 3.5 | 84.6 | 27 |

### Q08: PASS

- Rows: 72 · Runtime: 20.7 ms · Errors: none
- Header says: *PASS. Freddie Freeman crosses 1,000 (2015+) hits in 2021.*
- Check: Freeman crosses 1,000 hits (2015+) in 2021 (1,048). 72 players.

| name | season_reached | cum_hits | cum_hr | cum_rbi |
|---|---|---|---|---|
| Charlie Blackmon | 2020 | 1007 | 150 | 442 |
| DJ LeMahieu | 2021 | 1126 | 86 | 439 |
| Eric Hosmer | 2021 | 1028 | 129 | 560 |
| Francisco Lindor | 2021 | 1000 | 158 | 474 |
| Freddie Freeman | 2021 | 1048 | 185 | 583 |

### Q09: PASS

- Rows: 116 · Runtime: 23.4 ms · Errors: none
- Header says: *PASS. Mike Trout: 2015–2020, 6 seasons, 44.1 WAR.*
- Check: Trout 2015–2020, 6 seasons, 44.1 WAR.

| name | streak_start | streak_end | seasons | streak_war |
|---|---|---|---|---|
| Mookie Betts | 2015 | 2025 | 11 | 60.7 |
| Francisco Lindor | 2015 | 2025 | 11 | 60.2 |
| Freddie Freeman | 2015 | 2025 | 11 | 53.2 |
| José Ramírez | 2016 | 2025 | 10 | 55.8 |
| Trea Turner | 2016 | 2025 | 10 | 47.2 |

### Q10: PASS

- Rows: 24 · Runtime: 32.6 ms · Errors: none
- Header says: *PASS. Top 3 cohorts are 1992, 1991, 1990 (ages covered 23–33, 24–34, 25–35), i.e. at peak age during the window.*
- Check: Top 3 cohorts 1992/1991/1990; covered ages centre on 28–30.

| birth_year | ages_covered | players | total_war | avg_war_per_player | players_20plus_war |
|---|---|---|---|---|---|
| 1992 | 23-33 | 246 | 904.9 | 3.68 | 15 |
| 1991 | 24-34 | 241 | 860.3 | 3.57 | 8 |
| 1990 | 25-35 | 248 | 856.1 | 3.45 | 10 |
| 1994 | 21-31 | 278 | 838.6 | 3.02 | 11 |
| 1993 | 22-32 | 264 | 823.4 | 3.12 | 9 |

### Q11: PASS

- Rows: 329 · Runtime: 25.4 ms · Errors: none
- Header says: *PASS. 217 of 329 rows (66%) within 5 wins, 309 (94%) within 10; implied_wins averages 1.9 below actual (excluded multi-team WAR).*
- Check: 217/329 (66%) within 5 wins, 309 (94%) within 10; implied averages 1.88 below actual. Caveat now names the dropped 2025 COL row.

| season_year | team | payroll_millions | team_war | wins | implied_wins | millions_per_war | cost_rank |
|---|---|---|---|---|---|---|---|
| 2025 | MIL | 140.3 | 45.5 | 97 | 93.2 | 3.08 | 1 |
| 2025 | MIA | 90.9 | 24.6 | 79 | 72.2 | 3.69 | 2 |
| 2025 | TBR | 102.8 | 25.5 | 77 | 73.2 | 4.03 | 3 |
| 2025 | CLE | 118.4 | 28.2 | 88 | 75.8 | 4.2 | 4 |
| 2025 | CIN | 135.8 | 31.8 | 83 | 79.4 | 4.27 | 5 |

### Q12a: PASS

- Rows: 20 · Runtime: 1.0 ms · Errors: none
- Header says: *PASS. 2016 TEX ranks 4th (+13.1 wins); 1st is 2021 SEA (+14.7).*
- Check: 2016 TEX #4 (+13.1). New `luck_per_162` column is the sort key; order is unchanged from before (×162 is monotonic), but 2020 MIA now visibly ranks #2 on +14.4/162 (+5.3 actual). LAD 2018 shows −11.5 wins vs −11.4/162 because it played 163.

| season_year | team | wins | losses | expected_wins | luck_wins | luck_per_162 |
|---|---|---|---|---|---|---|
| 2021 | SEA | 90 | 72 | 75.3 | 14.7 | 14.7 |
| 2020 | MIA | 31 | 29 | 25.7 | 5.3 | 14.4 |
| 2017 | SDP | 71 | 91 | 57.3 | 13.7 | 13.7 |
| 2016 | TEX | 95 | 67 | 81.9 | 13.1 | 13.1 |
| 2018 | SEA | 89 | 73 | 77.0 | 12.0 | 12.0 |

### Q12b: FINDING

- Rows: 3 · Runtime: 0.9 ms · Errors: none
- Header says: *Finding, not the expected result. Lucky (+0.2 next season, n=50) and Neutral (+0.2, n=191) regress to ~0, but the Unlucky bucket persists: -1.5 wins/162 next season (n=59, SE 0.46, ~3.3 SE from 0). Causes (e.g. bullpen quality, roster continuity) are not tested here. Three buckets were compared, so treat one ~3 SE result with that multiple-comparison context in mind.*
- Check: The original expectation ("near 0 for all buckets") failed for the Unlucky bucket; the Verified line now records the finding (−1.5, SE 0.46, ~3.3 SE, n=59; causes untested; 3 buckets compared).

| bucket | team_seasons | avg_luck | avg_next_season_luck |
|---|---|---|---|
| 1: Lucky (4+ wins over) | 50 | 6.7 | 0.2 |
| 2: Neutral | 191 | 0.0 | 0.2 |
| 3: Unlucky (4+ wins under) | 59 | -6.5 | -1.5 |

### Q13: PASS

- Rows: 8 · Runtime: 15.9 ms · Errors: none
- Header says: *PASS. 120+ tier declines for both: movers -19.4, stayers -16.6.*
- Check: 120+ tier declines for both (movers −19.4, stayers −16.6).

| prior_tier | grp | player_pairs | avg_prev_wrc_plus | avg_next_wrc_plus | avg_change |
|---|---|---|---|---|---|
| 1: 120+ | Changed teams | 60 | 134.7 | 115.3 | -19.4 |
| 1: 120+ | Stayed | 495 | 137.1 | 120.5 | -16.6 |
| 2: 100-119 | Changed teams | 80 | 109.2 | 102.4 | -6.7 |
| 2: 100-119 | Stayed | 483 | 109.4 | 107.7 | -1.7 |
| 3: 80-99 | Changed teams | 81 | 89.8 | 98.4 | 8.6 |

### Q14: PASS

- Rows: 66 · Runtime: 11.4 ms · Errors: none
- Header says: *PASS. The positional adjustment is designed to equalize positions, so differences reflect talent concentration in this window: SS (2.60 WAR/600 decade mean) and 3B (2.52) deepest, 1B thinnest (1.61).*
- Check: Decade means of WAR/600: SS 2.60, 3B 2.52, 2B 1.96, OF 1.92, C 1.82, 1B 1.61. The positional adjustment is designed to equalize positions, so the spread reflects talent concentration in this window, not positional value. Earlier "matches the 1B adjustment" claim removed.

| pos | season_year | players | war_per_600 | vs_decade_avg | yoy_change |
|---|---|---|---|---|---|
| 1B | 2015 | 45 | 2.17 | 0.56 | None |
| 1B | 2016 | 48 | 1.2 | -0.41 | -0.97 |
| 1B | 2017 | 40 | 2.04 | 0.43 | 0.84 |
| 1B | 2018 | 40 | 1.61 | -0.0 | -0.43 |
| 1B | 2019 | 49 | 1.33 | -0.29 | -0.29 |

### Q15: PASS

- Rows: 25 · Runtime: 33.8 ms · Errors: none
- Header says: *PASS. List includes award years: Harper 2015 (MVP), Arrieta 2015 (CY), deGrom 2018 (CY), Bellinger 2019 (MVP), Acuna 2023 (MVP).*
- Check: Award seasons in list: Harper 2015, Arrieta 2015, deGrom 2018, Bellinger 2019, Acuña 2023.

| name | season_year | war | avg_other_seasons | delta | n_seasons |
|---|---|---|---|---|---|
| Chris Davis | 2015 | 5.4 | -0.7 | 6.1 | 5 |
| Geraldo Perdomo | 2025 | 7.1 | 1.2 | 5.9 | 5 |
| Jacob deGrom | 2018 | 9.4 | 3.7 | 5.7 | 10 |
| Ronald Acuña Jr. | 2023 | 9.1 | 3.4 | 5.7 | 7 |
| AJ Pollock | 2015 | 6.8 | 1.2 | 5.6 | 8 |

### Q16: PASS

- Rows: 48 · Runtime: 43.3 ms · Errors: none
- Header says: *PASS (finding). MI/CI peak at 26-27 (smoothed: MI 27, CI 26). C and OF show no improvement after their first qualifying age, likely selection: the first season of a pair needs 200+ PA, so it skews good. No peak-age claim is made for C or OF. Naive column stays flat at older ages (survivorship contrast holds).*
- Check: Recorded as a finding. Smoothed peaks: MI 27 (+5.7), CI 26 (+4.6). C and OF show no improvement after their first qualifying age (C 25, OF 23), likely selection: a pair's first season needs 200+ PA, so it skews good. No peak-age claim for C/OF. Naive column stays flat at older ages (OF 99.7 → 104.8), so the survivorship contrast holds.

| pos_group | age | n_pairs | avg_change_into_age | cumulative_curve | smoothed_change | smoothed_curve | naive_avg_wrc_plus |
|---|---|---|---|---|---|---|---|
| C | 25 | 25 | -0.9 | -0.9 | -2.6 | -2.6 | 95.2 |
| C | 26 | 29 | -4.4 | -5.2 | -1.8 | -4.4 | 91.5 |
| C | 27 | 32 | -0.1 | -5.3 | -2.2 | -6.6 | 92.5 |
| C | 28 | 36 | -2.2 | -7.5 | -0.6 | -7.2 | 89.5 |
| C | 29 | 33 | 0.4 | -7.1 | 2.0 | -5.2 | 90.7 |

### Q17: PASS

- Rows: 25 · Runtime: 9.6 ms · Errors: none
- Header says: *PASS. Tucker has 5 seasons of 300+ PA (excluding 2020), avg WAR 4.7, matches FanGraphs (query: mean 4.69, sd 0.31).*
- Check: Human check done: Tucker has 5 seasons of 300+ PA (excluding 2020), avg WAR 4.7, matches. Query shows mean 4.69, sd 0.31.

| player_id | name | n_seasons | mean_war | var_war | sd_war |
|---|---|---|---|---|---|
| 18345 | Kyle Tucker | 5 | 4.69 | 0.1 | 0.31 |
| 19290 | Randy Arozarena | 5 | 2.91 | 0.48 | 0.7 |
| 11609 | Willson Contreras | 8 | 2.51 | 0.5 | 0.71 |
| 19197 | Will Smith | 5 | 3.9 | 0.6 | 0.78 |
| 16997 | Gleyber Torres | 7 | 2.54 | 0.67 | 0.82 |

### Q18: PASS

- Rows: 5 · Runtime: 18.0 ms · Errors: none
- Header says: *PASS. Reviewed the comps, they fit Freeman 2023's hitter profile (K 16.6%, BB 9.9%, ISO .235, 161 wRC+) -> Altuve 2022, Guerrero Jr. 2024, Cabrera 2016, Tucker 2021, Alvarez 2024.*
- Check: Human check done: reviewed the comps, they fit Freeman 2023's hitter profile (high contact, above-average walk, .22–.26 ISO, 146–167 wRC+).

| name | season_year | k_pct | bb_pct | iso | wrc_plus | distance_sq |
|---|---|---|---|---|---|---|
| Jose Altuve | 2022 | 14.4 | 10.9 | 0.233 | 164 | 0.264 |
| Vladimir Guerrero Jr. | 2024 | 13.8 | 10.3 | 0.221 | 164 | 0.416 |
| Miguel Cabrera | 2016 | 17.1 | 11.0 | 0.247 | 153 | 0.593 |
| Kyle Tucker | 2021 | 15.9 | 9.3 | 0.263 | 146 | 0.621 |
| Yordan Alvarez | 2024 | 15.0 | 10.9 | 0.259 | 167 | 0.627 |

### Q19: PASS

- Rows: 3 · Runtime: 6.7 ms · Errors: none
- Header says: *PASS. FIP beats ERA in all buckets; widest gaps in bucket 1 (0.83 vs 1.16) and bucket 3 (0.77 vs 1.06).*
- Check: FIP beats ERA in all buckets; widest gaps in buckets 1 and 3.

| bucket | pitcher_pairs | avg_era | avg_fip | avg_next_era | mae_era_as_predictor | mae_fip_as_predictor |
|---|---|---|---|---|---|---|
| 1: ERA well below FIP (lucky) | 60 | 3.14 | 4.16 | 4.16 | 1.16 | 0.83 |
| 2: Within 0.75 | 553 | 3.85 | 3.91 | 4.01 | 0.8 | 0.76 |
| 3: ERA well above FIP (unlucky) | 55 | 4.93 | 3.92 | 4.16 | 1.06 | 0.77 |

### Q20: PASS

- Rows: 121 · Runtime: 19.4 ms · Errors: none
- Header says: *PASS. 2017 rank 1 = Giancarlo Stanton, 59 HR (MIA). 121 rows (110 under ROW_NUMBER); the 11 extra are ties at #10: 2017 +1, 2018 +1, 2020 +4 (six players tied at 16 HR for 7th), 2021 +2, 2023 +1, 2025 +2.*
- Check: Now RANK() instead of ROW_NUMBER(), so ties at #10 are kept: 121 rows (was 110). Extra rows: 2017 +1, 2018 +1, 2020 +4 (six tied at 16 HR for 7th → 14 rows), 2021 +2, 2023 +1, 2025 +2. 2017 #1 = Giancarlo Stanton, 59 HR (MIA).

| season_year | hr_rank | full_name | team_id | home_runs |
|---|---|---|---|---|
| 2025 | 1 | Cal Raleigh | SEA | 60 |
| 2025 | 2 | Kyle Schwarber | PHI | 56 |
| 2025 | 3 | Shohei Ohtani | LAD | 55 |
| 2025 | 4 | Aaron Judge | NYY | 53 |
| 2025 | 5 | Eugenio Suárez | None | 49 |

## 6. Open items

None. O1 (Q20 ties), O2 (Q16 C/OF curves), O3 (Q14 catchers) and O4 (human checks) were resolved in the final review; see section 4b.

## 7. Resolved from the first review

| Flag | Resolution |
|---|---|
| L1 DH in position set | Excluded (decision 1) |
| L2 one-member PERCENT_RANK partitions | DH removed + ≥ 10 floor (decision 2) |
| L3 Q12a sort vs display mismatch | `luck_per_162` shown and used as sort key (decision 3) |
| L4 Q11 silent drop | Caveat added (decision 5) |
| L5 name-keyed params | Q18 keyed on player_id (decision 8); Q05 still takes a name but returns one block per player_id |
| L6 Q16 interpretation | Caveat rewritten, smoothing added (decision 6); curve shape recorded as a finding (change 14) |

2026-09-28: Q05 re-keyed from full_name to player_id (params CTE target_player_id = 13611, Mookie Betts; WHERE p.player_id = ...); Q18 gained p.player_id as its first output column. Re-verified: Q05 returns the same 11 rows with identical values and order; Q18 for Freeman 2023 returns the same 5 comps (Altuve 2022, Guerrero Jr. 2024, Cabrera 2016, Tucker 2021, Alvarez 2024) in the same order with the same distance_sq (0.264, 0.416, 0.593, 0.621, 0.627).
