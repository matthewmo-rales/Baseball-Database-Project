"""Plotly figures (built here in Python, rendered by static/js/charts.js) and the
same-origin plotly.js bundle.

Chart definitions (the reference for app/stats.py as well):

- Metric: combined WAR (batting + pitching via UNION ALL, exactly as Q05)
  scaled to 162 games, war * 162.0 / scheduled_games.
- Baseline (player chart only): per season, a leave-one-out mean,
  (group sum - own) / (n - 1), where "own" applies only when the player is
  in that season's group.
- Groups: qualified hitters (PA >= 3.1 * scheduled games) with the same
  primary_position, for C/1B/2B/3B/SS/OF; for P, qualified pitchers
  (outs >= 3 * scheduled games) listed at P only, still on combined WAR.
  DH, IF and NULL get no baseline.
- Minimum: a baseline point is drawn only when at least 5 OTHER qualified
  players are in the group; otherwise the line has a gap.
- The compare chart shows the two players' lines only, no baseline.
- Batting rows shown on the player, season and compare pages: PA > 0, plus
  PA = 0 rows when the player has no pitching row that season (pitchers'
  0-PA placeholder rows stay hidden). stats.SHOWN_BATTING_ROW holds the rule.

CSP: plotly.js normally injects a <style> element, which style-src 'self'
blocks. It skips that step when an element with id "plotly.js-style-global"
and class "no-inline-styles" already exists, so chart pages link
/vendor/plotly.css under that id. The CSS is the rule table plotly.js would
have injected, extracted from the installed bundle at startup, so it always
matches the served plotly.js and style-src stays 'self'. The bundled MapLibre
gets the same treatment (/vendor/maplibre.css under its own element id).
"""
import logging
import re

import plotly
import plotly.graph_objects as go
from flask import Blueprint, current_app
from plotly.offline import get_plotlyjs

bp = Blueprint("charts", __name__)
log = logging.getLogger(__name__)

# Okabe-Ito (colorblind-safe). Dash and marker also differ per series, so
# nothing depends on color alone.
PLAYER_STYLE = {"color": "#0072B2", "dash": "solid", "symbol": "circle"}
BASELINE_STYLE = {"color": "#E69F00", "dash": "dash", "symbol": "diamond"}
SECOND_STYLE = {"color": "#D55E00", "dash": "dot", "symbol": "square"}
GRID = "rgba(128, 128, 128, 0.25)"
ZERO_LINE = "rgba(128, 128, 128, 0.7)"
TRANSPARENT = "rgba(0, 0, 0, 0)"
SHORT_SEASON = 2020
SHORT_SEASON_TEXT = "2020: 60 games, scaled to 162"
CACHE_MAX_AGE = 31536000   # one year; URLs carry ?v=<plotly version>


# ---------------------------------------------------------------- figures

def _player_trace(name, series, style):
    return go.Scatter(
        x=[r["season_year"] for r in series],
        y=[r["war162"] for r in series],
        customdata=[r["war"] for r in series],
        name=name,
        mode="lines+markers",
        line={"color": style["color"], "dash": style["dash"], "width": 2.5},
        marker={"symbol": style["symbol"], "size": 8, "color": style["color"]},
        hovertemplate=(
            "%{x}<br>WAR %{customdata:.1f}<br>WAR per 162 %{y:.1f}<extra>%{fullData.name}</extra>"
        ),
    )


def _baseline_trace(name, series):
    return go.Scatter(
        x=[r["season_year"] for r in series],
        y=[r["war162"] for r in series],
        customdata=[r["others"] for r in series],
        name=name,
        mode="lines+markers",
        connectgaps=False,      # no point where too few others qualify
        line={"color": BASELINE_STYLE["color"], "dash": BASELINE_STYLE["dash"], "width": 2},
        marker={"symbol": BASELINE_STYLE["symbol"], "size": 6, "color": BASELINE_STYLE["color"]},
        hovertemplate=(
            "%{x}<br>Mean WAR per 162 %{y:.1f}<br>%{customdata} other qualified players"
            "<extra>%{fullData.name}</extra>"
        ),
    )


# ---------------------------------------------------------------- titles
# Chart titles are not part of the Plotly layout: templates render them as an
# HTML heading above the chart (autoescaped, and it wraps at narrow widths).
# These are Jinja globals (see init_app), so the words live here, next to the
# figures they describe.

def player_war_title(name):
    return name + ": WAR per 162 games"


def compare_war_title(name1, name2):
    return f"{name1} vs {name2}: WAR per 162 games"


QUERY_CHART_TITLES = {
    "woba_leaderboard": lambda season: "Top wOBA, qualified hitters, "
                                       + (str(season) if season is not None else "—"),
    "payroll_vs_win_pct": lambda season: "Payroll vs win %, "
                                         + (str(season) if season is not None else "all seasons"),
    "age_curves": lambda season: "Hitter aging: change in wRC+ into each age (delta method)",
    "birth_cohorts": lambda season: "Total WAR by birth cohort, 2015–2025",
}


def query_chart_title(name, season=None):
    """Title of a saved-query chart. season is the season the chart shows
    (for woba_leaderboard with no filter, the latest season in the output;
    '—' when there is none)."""
    return QUERY_CHART_TITLES[name](season)


def _styled(traces, xaxis, yaxis, height=440, margin_left=60, margin_right=20, margin_bottom=90):
    """A figure with the shared look: transparent, labeled, no template.
    No title (see above); the top margin leaves room for the 2020 note."""
    fig = go.Figure(data=traces)
    fig.update_layout(
        template="none",
        font={"family": 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif', "size": 13},
        xaxis={"gridcolor": GRID, "zeroline": False, **xaxis},
        yaxis={"gridcolor": GRID, **yaxis},
        paper_bgcolor=TRANSPARENT,
        plot_bgcolor=TRANSPARENT,
        hovermode="closest",
        legend={"orientation": "h", "x": 0, "y": -0.2, "yanchor": "top"},
        margin={"l": margin_left, "r": margin_right, "t": 40, "b": margin_bottom},
        height=height,
    )
    return fig


def _figure(traces, seasons):
    fig = _styled(
        traces,
        xaxis={"title": {"text": "Season"}, "dtick": 1},
        yaxis={"title": {"text": "WAR per 162 games"}, "rangemode": "tozero",
               "zeroline": True, "zerolinecolor": ZERO_LINE},
    )
    if seasons and min(seasons) <= SHORT_SEASON <= max(seasons):
        fig.add_vline(x=SHORT_SEASON, line={"color": ZERO_LINE, "dash": "dot", "width": 1})
        fig.add_annotation(
            x=SHORT_SEASON, xref="x", y=1, yref="paper", yanchor="bottom",
            text=SHORT_SEASON_TEXT, showarrow=False,
        )
    return fig


def player_war_figure(player, series, baseline, baseline_name):
    traces = [_player_trace(player["full_name"], series, PLAYER_STYLE)]
    if baseline and any(r["war162"] is not None for r in baseline):
        traces.append(_baseline_trace(baseline_name, baseline))
    seasons = [r["season_year"] for r in series]
    return _figure(traces, seasons)


def compare_war_figure(p1, s1, p2, s2):
    traces = [
        _player_trace(f"{p1['full_name']} ({p1['player_id']})", s1, PLAYER_STYLE),
        _player_trace(f"{p2['full_name']} ({p2['player_id']})", s2, SECOND_STYLE),
    ]
    seasons = [r["season_year"] for r in s1] + [r["season_year"] for r in s2]
    return _figure(traces, seasons)


# ---------------------------------------------------------------- saved-query charts
# Each builder takes the Result that queries.execute() returned for its query
# (already season-filtered by the caller where a filter applies) and never
# runs SQL of its own. Registered by name in queries.REGISTRY (Entry.chart).

GROUP_STYLES = [   # Okabe-Ito colour, plus dash and marker so colour isn't needed
    {"color": "#0072B2", "dash": "solid", "symbol": "circle"},
    {"color": "#E69F00", "dash": "dash", "symbol": "square"},
    {"color": "#009E73", "dash": "dot", "symbol": "diamond"},
    {"color": "#CC79A7", "dash": "dashdot", "symbol": "triangle-up"},
]


def woba_leaderboard(result, season=None):
    """Q01: one season's wOBA leaders as horizontal bars (default: latest).

    Bars sit at positions 0..n-1 labelled with names, so two players who
    share a name still get separate bars, and tied ranks both show.
    """
    rows = result.records()
    if season is None and rows:
        season = max(r["season_year"] for r in rows)
    rows = sorted((r for r in rows if r["season_year"] == season),
                  key=lambda r: (r["woba_rank"], -r["woba"]))
    positions = list(range(len(rows)))
    trace = go.Bar(
        x=[r["woba"] for r in rows],
        y=positions,
        orientation="h",
        marker={"color": PLAYER_STYLE["color"]},
        text=[f"{r['woba']:.3f}" for r in rows],
        textposition="outside",
        cliponaxis=False,       # labels may sit in the right margin (see margin_right below)
        customdata=[[r["woba_rank"], r["name"], r["team"], r["pa"], r["wrc_plus"], r["player_id"]]
                    for r in rows],
        hovertemplate=("%{customdata[1]} (%{customdata[2]})<br>Player ID %{customdata[5]}"
                       "<br>Rank %{customdata[0]}<br>wOBA %{x:.3f}<br>wRC+ %{customdata[4]}"
                       "<br>PA %{customdata[3]}<extra></extra>"),
        name="wOBA",
    )
    fig = _styled(
        [trace],
        xaxis={"title": {"text": "wOBA"}, "rangemode": "tozero"},
        yaxis={"title": {"text": "Hitter (rank order)"}, "tickvals": positions,
               "ticktext": [r["name"] for r in rows], "autorange": "reversed"},
        margin_left=170,
        margin_right=60,        # room for the longest outside label, e.g. 0.463
    )
    fig.update_layout(showlegend=False)
    return fig


def payroll_vs_win_pct(result, season=None):
    """Q03: win% against payroll relative to that season's league average.
    2020 gets its own hollow-marker series. No trendline."""
    rows = result.records()
    full = [r for r in rows if r["season_year"] != SHORT_SEASON]
    short = [r for r in rows if r["season_year"] == SHORT_SEASON]

    def trace(points, name, symbol, color):
        return go.Scatter(
            x=[r["payroll_vs_league_avg"] for r in points],
            y=[r["win_pct"] for r in points],
            mode="markers",
            name=name,
            marker={"symbol": symbol, "size": 9, "color": color, "line": {"width": 1.5, "color": color}},
            customdata=[[r["team"], r["season_year"], r["payroll_millions"], r["wins"], r["losses"]]
                        for r in points],
            hovertemplate=("%{customdata[0]} %{customdata[1]}<br>Payroll $%{customdata[2]:.1f}M"
                           " (%{x:.2f}x league avg)<br>%{customdata[3]}-%{customdata[4]}, win% %{y:.3f}"
                           "<extra></extra>"),
        )

    traces = []
    if full:
        label = str(season) if season is not None else "162-game seasons"
        traces.append(trace(full, label, "circle", PLAYER_STYLE["color"]))
    if short:
        traces.append(trace(short, "2020 (60 games, prorated payroll)", "circle-open",
                            SECOND_STYLE["color"]))
    fig = _styled(
        traces,
        # Fixed text, no data in it: one fixed break so it fits at phone width.
        xaxis={"title": {"text": "Payroll relative to that season's<br>league average (1.0 = average)"}},
        yaxis={"title": {"text": "Win %"}},
        margin_bottom=140,
    )
    # Legend pinned to the bottom of the figure, clear of the two-line axis
    # title (it wraps to two rows at phone width).
    fig.update_layout(legend={"yref": "container", "y": 0, "yanchor": "bottom"})
    return fig


def age_curves(result, season=None):
    """Q16: per-age change in wRC+ by position group, as Q16 computes it.
    Raw delta-method averages as markers, Q16's 3-age smoothing as the line.
    Q16's cumulative columns are deliberately not plotted."""
    rows = result.records()
    groups = list(dict.fromkeys(r["pos_group"] for r in rows))
    traces = []
    for i, group in enumerate(groups):
        style = GROUP_STYLES[i % len(GROUP_STYLES)]
        points = [r for r in rows if r["pos_group"] == group]
        ages = [r["age"] for r in points]
        custom = [[r["n_pairs"], r["avg_change_into_age"], r["smoothed_change"]] for r in points]
        hover = ("%{fullData.legendgroup}, age %{x}<br>Raw change %{customdata[1]:+.1f}"
                 "<br>Smoothed change %{customdata[2]:+.1f}<br>%{customdata[0]} player pairs<extra></extra>")
        traces.append(go.Scatter(
            x=ages, y=[r["smoothed_change"] for r in points], customdata=custom,
            mode="lines", name=group, legendgroup=group,
            line={"color": style["color"], "dash": style["dash"], "width": 2.5},
            hovertemplate=hover,
        ))
        traces.append(go.Scatter(
            x=ages, y=[r["avg_change_into_age"] for r in points], customdata=custom,
            mode="markers", name=group + " (raw)", legendgroup=group, showlegend=False,
            marker={"color": style["color"], "symbol": style["symbol"], "size": 8},
            hovertemplate=hover,
        ))
    return _styled(
        traces,
        xaxis={"title": {"text": "Age"}, "dtick": 1},
        yaxis={"title": {"text": "Change in wRC+ from the previous age"},
               "zeroline": True, "zerolinecolor": ZERO_LINE},
    )


def birth_cohorts(result, season=None):
    """Q10: total 2015-2025 WAR by birth year; WAR per player on hover."""
    rows = sorted(result.records(), key=lambda r: r["birth_year"])
    trace = go.Bar(
        x=[r["birth_year"] for r in rows],
        y=[r["total_war"] for r in rows],
        marker={"color": PLAYER_STYLE["color"]},
        customdata=[[r["avg_war_per_player"], r["players"], r["ages_covered"]] for r in rows],
        hovertemplate=("Born %{x}<br>Total WAR %{y:.1f}<br>WAR per player %{customdata[0]:.2f}"
                       "<br>%{customdata[1]} players, ages %{customdata[2]} in the data<extra></extra>"),
        name="Total WAR",
    )
    fig = _styled(
        [trace],
        xaxis={"title": {"text": "Birth year (cohort)"}, "dtick": 1},
        yaxis={"title": {"text": "Total WAR, 2015–2025"}, "rangemode": "tozero"},
    )
    fig.update_layout(showlegend=False)
    return fig


QUERY_CHARTS = {
    "woba_leaderboard": woba_leaderboard,
    "payroll_vs_win_pct": payroll_vs_win_pct,
    "age_curves": age_curves,
    "birth_cohorts": birth_cohorts,
}


def figure_response(fig):
    return current_app.response_class(fig.to_json(), mimetype="application/json")


# ---------------------------------------------------------------- vendored assets

# The rule table in the bundle looks like: NAME={"X,X div":"...", ...};for(K in NAME)
# where X / Y stand for the two root selectors below.
_RULES_RE = re.compile(r'(\w+)=(\{"X,X div":.*?\});for\(\w+ in \1\)', re.S)
_STR = r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\''
_PAIR_RE = re.compile(r"(" + _STR + r"|[A-Za-z_$][\w$]*)\s*:\s*(" + _STR + r")")
_ROOTS = {"X": ".js-plotly-plot .plotly", "Y": ".plotly-notifier"}


def _unquote(token):
    if token[0] in "\"'":
        return re.sub(r"\\(.)", r"\1", token[1:-1])
    return token


def plotly_css_from_bundle(js):
    """The CSS plotly.js would inject, as a stylesheet. '' if not found."""
    match = _RULES_RE.search(js)
    if not match:
        return ""
    rules = []
    for key, value in _PAIR_RE.findall(match.group(2)):
        selector = re.sub(r"^,", " ,", _unquote(key))
        selector = selector.replace("X", _ROOTS["X"]).replace("Y", _ROOTS["Y"])
        rules.append(selector + "{" + _unquote(value) + "}")
    # plotly.js calls insertRule(rule, 0) for each in turn, so its live sheet
    # holds them in reverse; keep that order so the cascade is identical.
    rules.reverse()
    header = f"/* Generated from the installed plotly.js bundle (plotly {plotly.__version__}, MIT). */\n"
    return header + "\n".join(rules) + "\n"


# The bundled MapLibre (map traces) injects its own <style id="<hex>"> at load
# unless an element with that id exists: var e=document.createElement("style");
# e.id="<hex>",e.textContent='<css>'. This app draws no maps, but serving that
# CSS under the same id keeps the console free of CSP violations.
_MAPLIBRE_RE = re.compile(
    r'var (\w+)=document\.createElement\("style"\);\1\.id="([0-9a-f]+)",'
    r"\1\.textContent='((?:[^'\\]|\\.)*)'"
)


def maplibre_css_from_bundle(js):
    """(element id, CSS) of MapLibre's injected stylesheet, or (None, '')."""
    match = _MAPLIBRE_RE.search(js)
    if not match:
        return None, ""
    return match.group(2), _unquote("'" + match.group(3) + "'") + "\n"


def init_app(app):
    """Read the bundle once at startup; derive the CSS from it."""
    js = get_plotlyjs()
    css = plotly_css_from_bundle(js)
    if not css:
        log.warning("plotly.js style rules not found; charts will render unstyled")
    maplibre_id, maplibre_css = maplibre_css_from_bundle(js)
    app.extensions["plotly_assets"] = {
        "js": js.encode("utf-8"),
        "css": css.encode("utf-8"),
        "maplibre_css": maplibre_css.encode("utf-8"),
    }
    # Globals, not a context processor: templates import the chart macros,
    # and imported macros don't see the render context.
    app.jinja_env.globals.update(
        plotly_version=plotly.__version__,
        plotly_maplibre_style_id=maplibre_id,
        player_war_title=player_war_title,
        compare_war_title=compare_war_title,
        query_chart_title=query_chart_title,
    )


def _asset(kind, mimetype):
    resp = current_app.response_class(
        current_app.extensions["plotly_assets"][kind], mimetype=mimetype
    )
    resp.headers["Cache-Control"] = f"public, max-age={CACHE_MAX_AGE}, immutable"
    return resp


@bp.route("/vendor/plotly.min.js")
def plotly_js():
    return _asset("js", "application/javascript")


@bp.route("/vendor/plotly.css")
def plotly_css():
    return _asset("css", "text/css")


@bp.route("/vendor/maplibre.css")
def maplibre_css():
    return _asset("maplibre_css", "text/css")
