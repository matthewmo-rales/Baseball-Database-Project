# Queries

All analytical SQL is in [queries/analysis.sql](queries/analysis.sql): 20 queries (Q01–Q20), with Q12 in two parts, so 21 query blocks. Per-query business questions, findings and caveats are in [queries/README.md](queries/README.md), and definitions of the advanced stats are in [queries/ADVANCED_STATS_EXPLAINED.md](queries/ADVANCED_STATS_EXPLAINED.md). This page is an overview.

## Four tiers

The queries are grouped by technique. **Tier 1** (Q01–Q04) covers joins, aggregation and ranking within a season. **Tier 2** (Q05–Q09) uses window functions: rolling averages, `LAG`, percentiles, running totals and a gaps-and-islands streak query. **Tier 3** (Q10–Q14) is multi-join business logic: combining batting and pitching WAR with `UNION ALL`, team-level cost and luck, and before/after comparisons with a control group. **Tier 4** (Q15–Q19) builds CTE pipelines for modeling-style questions: leave-one-out baselines, delta-method aging curves, variance, nearest-neighbor comps and a regression check. Q20 is an additional leaderboard. SQLite has no `QUALIFY`, `STDDEV` or `CORR`, so the queries use window functions in CTEs and compute variance as `AVG(x*x) - AVG(x)*AVG(x)`.

Several queries in the original project brief needed data this database doesn't have (individual salaries, injury lists, draft data, pre/post-trade splits). Each was replaced with the closest question the data can answer; the list is in [queries/README.md](queries/README.md#scope-changes).

## Highlights

- **Q12b, Pythagorean luck persistence:** teams that beat their run differential regressed to about zero the next season, but teams that fell short of it stayed below it on average, which was not the expected result. The query's header records the result with its standard error and a note on multiple comparisons.
- **Q13, team changes:** hitters who changed teams are compared with hitters of the same prior-season quality who stayed, so regression to the mean isn't mistaken for a team-change effect.
- **Q16, aging curves:** the delta method (paired consecutive seasons of the same player) sits next to a naive average by age, which shows the survivorship bias the naive version has.

## How results are verified

Every query's header has a `Verified:` line with a real-world fact checked against the output (for example, a season leader). [queries/VERIFY.md](queries/VERIFY.md) records each query's row count, sample output and checks. The app runs the same SQL: it parses `analysis.sql` at startup, and a test (`test_real_db_row_counts_match_verify_md` in `tests/test_queries.py`) runs every saved query against the built database and fails if any row count differs from VERIFY.md. Queries that need payroll are skipped when payroll isn't loaded, and the test is skipped when the database hasn't been built.
