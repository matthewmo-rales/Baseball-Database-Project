"""Route fuzzing: every rule in app.url_map, bad values in every path and
query parameter. Never a 500, never a traceback; only friendly 400/404/405/413
pages (JSON endpoints share the same friendly error pages)."""
import re
from urllib.parse import quote

import pytest

HANK = 900010
OVER_SQLITE_MAX = "99999999999999999999"          # > 2**63 - 1
BAD_VALUES = [
    "999999999",            # nonexistent id
    "0",
    "-1",
    OVER_SQLITE_MAX,
    "9" * 5000,
    "x" * 5000,
    "ünïcødé 名前 🙂",
    "%00",
    "\x00",
    "'; DROP TABLE players; --",
    '"quoted"',
    "../../etc/passwd",
    "..",
]
QUERY_ARGS = ["q", "p1", "p2", "player_id", "season"]
# a valid value for every path variable, so each can be fuzzed alone
VALID_PATH = {"player_id": str(HANK), "year": "2015", "note_id": "1", "slug": "top-woba-by-season",
              "team_id": "TSA", "filename": "css/style.css"}
# companions that get a route past its first check, so later params are reached
COMPANIONS = [{}, {"player_id": str(HANK)}, {"p1": str(HANK)}, {"p2": str(HANK)}]
ALLOWED = {200, 400, 404, 405, 413}


def rules(app):
    return [r for r in app.url_map.iter_rules() if r.endpoint != "static"]


def build(rule, values):
    path = rule.rule
    for name in rule.arguments:
        path = re.sub(r"<(?:[^:<>]+:)?" + name + ">", values[name], path)
    return path


def check(resp, url):
    body = resp.get_data(as_text=True)
    assert resp.status_code in ALLOWED, f"{resp.status_code} for {url!r}"
    assert "Traceback" not in body and "Werkzeug Debugger" not in body, url


def base_paths(app):
    """Every rule with valid path values; every saved-query slug too."""
    slugs = list(app.extensions["saved_queries"])
    paths = []
    for rule in rules(app):
        if "slug" in rule.arguments:
            paths += [build(rule, {**VALID_PATH, "slug": s}) for s in slugs]
        else:
            paths.append(build(rule, VALID_PATH))
    return paths


def test_path_parameters(app, client):
    for rule in rules(app) + [r for r in app.url_map.iter_rules() if r.endpoint == "static"]:
        for name in rule.arguments:
            for bad in BAD_VALUES:
                url = build(rule, {**VALID_PATH, name: quote(bad, safe="")})
                check(client.get(url), url)
                if "POST" in rule.methods:
                    check(client.post(url), url)


def test_query_parameters(app, client):
    for path in base_paths(app):
        for companion in COMPANIONS:
            for arg in QUERY_ARGS:
                if arg in companion:
                    continue
                for bad in BAD_VALUES:
                    resp = client.get(path, query_string={**companion, arg: bad})
                    check(resp, f"{path}?{companion} {arg}={bad[:20]!r}")


def test_unknown_query_args_are_ignored(app, client):
    for path in base_paths(app):
        check(client.get(path, query_string={"sql": "SELECT 1", "x": OVER_SQLITE_MAX}), path)


@pytest.mark.parametrize("url", [
    f"/player/{OVER_SQLITE_MAX}",
    f"/player/{OVER_SQLITE_MAX}/season/2015",
    f"/player/{HANK}/season/{OVER_SQLITE_MAX}",
    f"/player/{OVER_SQLITE_MAX}/war-chart.json",
    f"/player/{OVER_SQLITE_MAX}/notes",
    f"/notes/{OVER_SQLITE_MAX}/edit",
])
def test_huge_path_integer_is_404(client, url):
    assert client.get(url).status_code == 404


@pytest.mark.parametrize("url", [
    f"/compare?p1={OVER_SQLITE_MAX}",
    f"/compare?p1={HANK}&p2={OVER_SQLITE_MAX}",
    f"/compare/war-chart.json?p1={HANK}&p2={OVER_SQLITE_MAX}",
    f"/query/career-war-trajectory?player_id={OVER_SQLITE_MAX}",
    f"/query/comparable-hitters?player_id={HANK}&season={OVER_SQLITE_MAX}",
    f"/query/top-woba-by-season?season={OVER_SQLITE_MAX}",
    f"/team/TSA?season={OVER_SQLITE_MAX}",
])
def test_huge_query_integer_is_400(client, url):
    assert client.get(url).status_code == 400
