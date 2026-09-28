"""Plotly figures (built here in Python, rendered by static/js/charts.js) and the
same-origin plotly.js bundle.

Chart definition: combined WAR (batting + pitching via
UNION ALL, exactly as Q05) scaled to 162 games, war * 162.0 / scheduled_games.
The player chart adds a per-season leave-one-out baseline: the mean of the
OTHER qualified hitters at the same unambiguous position (C/1B/2B/3B/SS/OF),
or of the other qualified pitchers listed at P, shown only when at least 5
others qualify. DH, IF and NULL get none. The compare chart has no baseline.

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


def _figure(title, traces, seasons):
    fig = go.Figure(data=traces)
    fig.update_layout(
        template="none",
        title={"text": title, "x": 0, "xanchor": "left"},
        font={"family": 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif', "size": 13},
        xaxis={"title": {"text": "Season"}, "dtick": 1, "gridcolor": GRID, "zeroline": False},
        yaxis={"title": {"text": "WAR per 162 games"}, "gridcolor": GRID, "rangemode": "tozero",
               "zeroline": True, "zerolinecolor": ZERO_LINE},
        paper_bgcolor=TRANSPARENT,
        plot_bgcolor=TRANSPARENT,
        hovermode="closest",
        legend={"orientation": "h", "x": 0, "y": -0.2, "yanchor": "top"},
        margin={"l": 60, "r": 20, "t": 80, "b": 90},
        height=440,
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
    return _figure(player["full_name"] + ": WAR per 162 games", traces, seasons)


def compare_war_figure(p1, s1, p2, s2):
    traces = [
        _player_trace(f"{p1['full_name']} ({p1['player_id']})", s1, PLAYER_STYLE),
        _player_trace(f"{p2['full_name']} ({p2['player_id']})", s2, SECOND_STYLE),
    ]
    seasons = [r["season_year"] for r in s1] + [r["season_year"] for r in s2]
    title = f"{p1['full_name']} vs {p2['full_name']}: WAR per 162 games"
    return _figure(title, traces, seasons)


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
