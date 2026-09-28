"""Saved queries: queries/analysis.sql parsed once at startup, plus the registry.

The file is the single source of SQL. REGISTRY below holds metadata only
(slug, query id, parameter specs, payroll flag), never SQL text. Startup
fails loudly if the file and the registry disagree, if a block isn't exactly
one complete WITH/SELECT statement, or if a params CTE doesn't match its
registry entry.

A params CTE such as
    WITH params AS (SELECT 5361 AS target_player_id,   -- Freddie Freeman
                           2023 AS target_season),
becomes
    WITH params AS (SELECT ? AS target_player_id, ? AS target_season),
and its literals become the query's example parameters. Every value a
request supplies is bound to a ?; request data never becomes SQL text.
"""
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUERIES_FILE = PROJECT_ROOT / "queries" / "analysis.sql"

MAX_DISPLAY_ROWS = 1000


class QueryFileError(Exception):
    """analysis.sql and the registry disagree, or a block is malformed."""


# ---------------------------------------------------------------- registry

@dataclass(frozen=True)
class ParamSpec:
    name: str       # column name in the params CTE
    type: type      # Python type the request value is converted to
    source: str     # request argument it comes from


PLAYER = ParamSpec("target_player_id", int, "player_id")
SEASON = ParamSpec("target_season", int, "season")


@dataclass(frozen=True)
class Entry:
    query_id: str
    params: tuple = ()
    requires_payroll: bool = False
    chart: str | None = None        # name of a builder in charts.QUERY_CHARTS


REGISTRY = {
    "top-woba-by-season":        Entry("Q01", chart="woba_leaderboard"),
    "top-war-by-position":       Entry("Q02"),
    "payroll-efficiency":        Entry("Q03", requires_payroll=True, chart="payroll_vs_win_pct"),
    "strikeout-leaders":         Entry("Q04"),
    "career-war-trajectory":     Entry("Q05", params=(PLAYER,)),
    "war-risers-and-fallers":    Entry("Q06"),
    "war-percentile-by-position": Entry("Q07"),
    "cumulative-career-totals":  Entry("Q08"),
    "war-streaks":               Entry("Q09"),
    "birth-cohort-war":          Entry("Q10", chart="birth_cohorts"),
    "team-cost-per-war":         Entry("Q11", requires_payroll=True),
    "pythag-luck":               Entry("Q12a"),
    "pythag-luck-persistence":   Entry("Q12b"),
    "team-change-impact":        Entry("Q13"),
    "position-value-trend":      Entry("Q14"),
    "breakout-seasons":          Entry("Q15"),
    "aging-curves":              Entry("Q16", chart="age_curves"),
    "war-consistency":           Entry("Q17"),
    "comparable-hitters":        Entry("Q18", params=(PLAYER, SEASON)),
    "era-fip-regression":        Entry("Q19"),
    "top-hr-by-season":          Entry("Q20"),
}


# ---------------------------------------------------------------- parsing

@dataclass
class Block:
    query_id: str
    title: str
    optional: bool
    tier: str
    fields: dict = field(default_factory=dict)
    sql: str = ""


@dataclass(frozen=True)
class SavedQuery:
    slug: str
    query_id: str
    title: str
    optional: bool
    tier: str
    business_question: str
    technique: str
    caveats: str
    verified: str
    sql: str                  # exactly what execute() runs
    params: tuple
    example: dict             # param name -> literal from the file
    requires_payroll: bool
    chart: str | None

    @property
    def example_args(self):
        """The file's example values keyed by request argument, for links."""
        return {spec.source: self.example[spec.name] for spec in self.params}


HEADER_RE = re.compile(r"^-- (Q\d{2}[a-z]?)( \(optional\))?: (.+)$")
FIELD_RE = re.compile(r"^-- (Business question|Technique|Caveats|Verified): ?(.*)$")
CONTINUATION_RE = re.compile(r"^--\s{2,}(\S.*)$")
RULER_RE = re.compile(r"^-- ?={10,}\s*$")
FIELD_KEYS = {
    "Business question": "business_question",
    "Technique": "technique",
    "Caveats": "caveats",
    "Verified": "verified",
}


def _is_comment_or_blank(line):
    stripped = line.strip()
    return not stripped or stripped.startswith("--")


def parse_blocks(text):
    """Split the file into query blocks, each with tier, header fields and SQL."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks = []
    tier = ""
    current = None
    body = []
    field_key = None
    in_header = False

    def finish():
        if current is not None:
            current.sql = _extract_sql(current.query_id, body)
            blocks.append(current)

    for i, line in enumerate(lines):
        # a section heading is a comment line sandwiched between two rulers
        if (0 < i < len(lines) - 1 and RULER_RE.match(lines[i - 1])
                and RULER_RE.match(lines[i + 1]) and line.startswith("--")):
            finish()
            current, body = None, []
            tier = line[2:].strip()
            continue
        header = HEADER_RE.match(line)
        if header:
            finish()
            current = Block(header.group(1), header.group(3).strip(), bool(header.group(2)), tier)
            body, field_key, in_header = [], None, True
            continue
        if current is None:
            continue
        if in_header:
            match = FIELD_RE.match(line)
            if match:
                field_key = FIELD_KEYS[match.group(1)]
                current.fields[field_key] = match.group(2).strip()
                continue
            match = CONTINUATION_RE.match(line)
            if match and field_key:
                current.fields[field_key] = (current.fields[field_key] + " " + match.group(1).strip()).strip()
                continue
            if line.startswith("--"):
                raise QueryFileError(f"{current.query_id}: unexpected header line {line!r}")
            in_header = False
        body.append(line)
    finish()
    return blocks


def _extract_sql(query_id, body_lines):
    """The block's SQL through its final semicolon; must be one WITH/SELECT."""
    text = "\n".join(body_lines).strip()
    end = text.rfind(";")
    if end == -1:
        raise QueryFileError(f"{query_id}: no terminating semicolon")
    trailing = text[end + 1:]
    if any(not _is_comment_or_blank(l) for l in trailing.split("\n")):
        raise QueryFileError(f"{query_id}: text after the final semicolon")
    sql = text[:end + 1]
    if not sqlite3.complete_statement(sql):
        raise QueryFileError(f"{query_id}: not a complete SQL statement")
    if not re.match(r"(WITH|SELECT)\b", sql, re.I):
        raise QueryFileError(f"{query_id}: must start with WITH or SELECT")
    # exactly one statement: the first complete prefix must be the whole thing
    for match in re.finditer(";", sql):
        prefix = sql[:match.end()]
        if sqlite3.complete_statement(prefix):
            rest = sql[match.end():]
            if any(not _is_comment_or_blank(l) for l in rest.split("\n")):
                raise QueryFileError(f"{query_id}: more than one statement")
            break
    return sql


# ---------------------------------------------------------------- params CTEs

PARAMS_CTE_RE = re.compile(
    r"WITH\s+params\s+AS\s*\(\s*SELECT\b([^()]*)\)\s*,[ \t]*(?:--[^\n]*)?", re.I
)
LITERAL_ITEM_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?|'(?:[^']|'')*')\s+AS\s+([A-Za-z_]\w*)\s*$", re.I
)


def _literal(token):
    if token.startswith("'"):
        return token[1:-1].replace("''", "'")
    return float(token) if "." in token else int(token)


def count_placeholders(sql):
    """'?' outside comments and string literals."""
    stripped = re.sub(r"'(?:[^']|'')*'|--[^\n]*|/\*.*?\*/", "", sql, flags=re.S)
    return stripped.count("?")


def bind_params_cte(query_id, sql, specs):
    """Replace the params CTE with ? placeholders; return (sql, example)."""
    matches = PARAMS_CTE_RE.findall(sql)
    if not specs:
        if matches:
            raise QueryFileError(f"{query_id}: has a params CTE but the registry declares no params")
        if count_placeholders(sql):
            raise QueryFileError(f"{query_id}: has ? placeholders but no params")
        return sql, {}
    if len(matches) != 1:
        raise QueryFileError(f"{query_id}: expected exactly one params CTE, found {len(matches)}")
    inner = re.sub(r"--[^\n]*", "", matches[0])
    items = [LITERAL_ITEM_RE.match(item) for item in inner.split(",")]
    if not all(items):
        raise QueryFileError(f"{query_id}: params CTE must be '<literal> AS <name>' items")
    names = [m.group(2) for m in items]
    expected = [spec.name for spec in specs]
    if names != expected:
        raise QueryFileError(f"{query_id}: params CTE names {names} != registry {expected}")
    example = {}
    for spec, m in zip(specs, items):
        value = _literal(m.group(1))
        if not isinstance(value, spec.type):
            raise QueryFileError(f"{query_id}: example {spec.name}={value!r} is not {spec.type.__name__}")
        example[spec.name] = value
    replacement = "WITH params AS (SELECT " + ", ".join(f"? AS {n}" for n in names) + "),"
    bound = PARAMS_CTE_RE.sub(lambda _: replacement, sql, count=1)
    if count_placeholders(bound) != len(specs):
        raise QueryFileError(f"{query_id}: placeholder count != {len(specs)} params")
    return bound, example


# ---------------------------------------------------------------- build

def build(blocks, registry=REGISTRY):
    by_id = {}
    for block in blocks:
        if block.query_id in by_id:
            raise QueryFileError(f"{block.query_id}: appears twice in the file")
        by_id[block.query_id] = block
    registry_ids = [entry.query_id for entry in registry.values()]
    missing_in_file = sorted(set(registry_ids) - set(by_id))
    missing_in_registry = sorted(set(by_id) - set(registry_ids))
    if missing_in_file:
        raise QueryFileError(f"registry ids not in analysis.sql: {missing_in_file}")
    if missing_in_registry:
        raise QueryFileError(f"analysis.sql ids not in the registry: {missing_in_registry}")
    if len(registry_ids) != len(set(registry_ids)):
        raise QueryFileError("a query id is registered under two slugs")

    saved = {}
    for slug, entry in registry.items():
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", slug):
            raise QueryFileError(f"slug {slug!r} is not kebab-case")
        block = by_id[entry.query_id]
        missing_fields = [k for k in FIELD_KEYS.values() if not block.fields.get(k)]
        if missing_fields:
            raise QueryFileError(f"{block.query_id}: header lacks {missing_fields}")
        sql, example = bind_params_cte(block.query_id, block.sql, entry.params)
        saved[slug] = SavedQuery(
            slug=slug, query_id=block.query_id, title=block.title, optional=block.optional,
            tier=block.tier, sql=sql, params=entry.params, example=example,
            requires_payroll=entry.requires_payroll, chart=entry.chart,
            **{k: block.fields[k] for k in FIELD_KEYS.values()},
        )
    return saved


def load(path=QUERIES_FILE, registry=REGISTRY):
    text = Path(path).read_text(encoding="utf-8")
    return build(parse_blocks(text), registry)


def slug_for(saved, query_id):
    """The registry slug for a query id (so pages link by id, not by slug text)."""
    return next(q.slug for q in saved.values() if q.query_id == query_id)


def by_tier(saved):
    """[(tier, [SavedQuery, ...]), ...] in file order."""
    groups = {}
    for query in sorted(saved.values(), key=_file_order):
        groups.setdefault(query.tier, []).append(query)
    return list(groups.items())


def _file_order(query):
    number = int(query.query_id[1:3])
    return (number, query.query_id[3:])


# ---------------------------------------------------------------- execution

@dataclass
class Result:
    columns: list
    rows: list          # every row the query returned (the page caps display)
    elapsed_ms: float

    @property
    def row_count(self):
        return len(self.rows)

    def index(self, column):
        return self.columns.index(column)

    def records(self):
        """Rows as dicts keyed by column name (for chart builders)."""
        return [dict(zip(self.columns, row)) for row in self.rows]


def execute(db, sql, params=()):
    """Run one registry SQL string with bound parameters. The only place
    saved-query SQL is executed; tests assert it only sees registry SQL."""
    start = time.perf_counter()
    cur = db.execute(sql, params)   # static-sql-allow: registry SQL parsed from analysis.sql at startup
    rows = cur.fetchall()
    elapsed = (time.perf_counter() - start) * 1000
    columns = [d[0] for d in cur.description]
    return Result(columns, rows, elapsed)


# Output columns that hold a season, for the post-query season filter.
SEASON_COLUMNS = ("season_year", "season")


def season_column(columns):
    """Index of the result's season column, or None."""
    return next((columns.index(c) for c in SEASON_COLUMNS if c in columns), None)


def filter_season(result, season):
    """A Result with only that season's rows (filtered in Python, after the
    query ran; the SQL is unchanged). season None returns result as-is."""
    if season is None:
        return result
    i = season_column(result.columns)
    return Result(result.columns, [r for r in result.rows if r[i] == season], result.elapsed_ms)


def check_charts(saved, builders):
    """Every chart hook names a builder, and charted queries take no params."""
    for q in saved.values():
        if q.chart and q.chart not in builders:
            raise QueryFileError(f"{q.query_id}: unknown chart builder {q.chart!r}")
        if q.chart and q.params:
            raise QueryFileError(f"{q.query_id}: charted queries must not take params")


def init_app(app):
    from .charts import QUERY_CHARTS
    saved = load(app.config.get("QUERIES_FILE", QUERIES_FILE))
    check_charts(saved, QUERY_CHARTS)
    app.extensions["saved_queries"] = saved
