"""WAR chart JSON, the vendored plotly.js, and its derived stylesheets."""
import json
import sqlite3

import pytest
from plotly.offline import get_plotlyjs

from app.charts import SHORT_SEASON_TEXT, maplibre_css_from_bundle, plotly_css_from_bundle

HANK, IVAN, JULES, KURT, LOU, MOE, NED, OTTO = range(900010, 900018)


def fig(client, url, status=200):
    resp = client.get(url)
    assert resp.status_code == status, url
    if status != 200:
        return None
    assert resp.mimetype == "application/json"
    return json.loads(resp.get_data(as_text=True))


def annotations(figure):
    return [a["text"] for a in figure["layout"].get("annotations", [])]


def test_player_chart_has_player_and_position_baseline(client):
    f = fig(client, f"/player/{HANK}/war-chart.json")
    player, baseline = f["data"]
    assert player["name"] == "Hank Baseline"
    assert player["x"] == [2015, 2016, 2017, 2020]
    assert player["y"] == pytest.approx([4.0, 3.0, 2.5, 1.5 * 162 / 60])   # 2020 scaled
    assert player["customdata"] == pytest.approx([4.0, 3.0, 2.5, 1.5])     # raw WAR on hover
    assert "customdata" in player["hovertemplate"] and "%{x}" in player["hovertemplate"]
    assert player["line"]["dash"] == "solid" and player["line"]["color"] == "#0072B2"
    assert player["marker"]["symbol"] == "circle"

    assert baseline["name"] == "Other qualified SS (mean)"
    assert baseline["line"]["dash"] == "dash" and baseline["line"]["color"] == "#E69F00"
    assert baseline["connectgaps"] is False
    assert "other qualified players" in baseline["hovertemplate"]
    assert baseline["x"] == [2015, 2016, 2017, 2020]
    # Others per season (Hank is in the group each time): 2015 Ivan, Jules and
    # 4 fillers; 2016 Jules and 4 fillers; 2017 nobody; 2020 4 fillers.
    assert baseline["customdata"] == [6, 5, 0, 4]
    # Leave-one-out: 2015 (20 - 4.0) / 6; 2016 (14 - 3.0) / 5, exactly 5 others
    assert baseline["y"][:2] == pytest.approx([16 / 6, 11 / 5])
    assert baseline["y"][2:] == [None, None]          # 0 and 4 others: hidden, a gap


def test_baseline_for_a_season_the_player_is_not_in_the_group(client):
    # Ivan qualified in 2015 only; 2016 (300 PA) and 2020 (100 PA) are not his
    _, baseline = fig(client, f"/player/{IVAN}/war-chart.json")["data"]
    assert baseline["x"] == [2015, 2016, 2017, 2020]
    assert baseline["customdata"] == [6, 6, 1, 5]
    assert baseline["y"][0] == pytest.approx((20 - 2.0) / 6)            # own row left out
    assert baseline["y"][1] == pytest.approx(14 / 6)                    # nothing to leave out
    assert baseline["y"][2] is None                                     # 1 other
    assert baseline["y"][3] == pytest.approx((4.05 + 4 * 0.5 * 162 / 60) / 5)


def test_baseline_trace_omitted_when_every_season_is_hidden(client, test_db_path):
    conn = sqlite3.connect(test_db_path)
    with conn:
        conn.execute("DELETE FROM batting_stats WHERE player_id BETWEEN 900020 AND 900023")
    conn.close()
    assert len(fig(client, f"/player/{HANK}/war-chart.json")["data"]) == 1


def test_axis_titles_title_and_transparent_background(client):
    f = fig(client, f"/player/{HANK}/war-chart.json")
    layout = f["layout"]
    assert layout["xaxis"]["title"]["text"] == "Season"
    assert layout["yaxis"]["title"]["text"] == "WAR per 162 games"
    assert "Hank Baseline" in layout["title"]["text"]
    assert layout["paper_bgcolor"] == layout["plot_bgcolor"] == "rgba(0, 0, 0, 0)"


def test_pitcher_baseline_is_other_qualified_p_only(client):
    f = fig(client, f"/player/{MOE}/war-chart.json")
    _, baseline = f["data"]
    assert baseline["name"] == "Other qualified P (mean)"
    assert baseline["x"] == [2015, 2016, 2017, 2020]
    # 2016 others: Ned 1.5 and 5 fillers (2, 2, 3, 1, 2). Otto (DH) qualifies
    # on outs with 5.5 combined WAR but is not listed at P, so he is excluded;
    # 900002 is P and qualifies but has no WAR.
    assert baseline["customdata"] == [0, 6, 0, 0]
    assert baseline["y"][1] == pytest.approx(11.5 / 6)
    assert baseline["y"][1] != pytest.approx((11.5 + 5.5) / 7)
    assert baseline["y"][0] is None and baseline["y"][2:] == [None, None]


def test_pitcher_baseline_uses_combined_war(client, test_db_path):
    # Give a filler starter 1.0 batting WAR in 2016; the baseline must include it.
    conn = sqlite3.connect(test_db_path)
    with conn:
        conn.execute("INSERT INTO batting_stats (player_id, season_year, team_id, plate_appearances,"
                     " at_bats, hits, war) VALUES (900030, 2016, 'TSB', 5, 5, 1, 1.0)")
    conn.close()
    _, baseline = fig(client, f"/player/{MOE}/war-chart.json")["data"]
    assert baseline["y"][1] == pytest.approx(12.5 / 6)


@pytest.mark.parametrize("player_id", [OTTO, LOU, KURT])   # DH, NULL, DH
def test_no_baseline_for_dh_or_null(client, player_id):
    f = fig(client, f"/player/{player_id}/war-chart.json")
    assert len(f["data"]) == 1


def test_two_way_chart_is_combined_war(client):
    f = fig(client, f"/player/{OTTO}/war-chart.json")
    assert f["data"][0]["customdata"] == pytest.approx([2.0 + 2.2, 2.5 + 3.0])


def test_2020_annotation_only_when_2020_is_in_range(client):
    assert SHORT_SEASON_TEXT in annotations(fig(client, f"/player/{HANK}/war-chart.json"))
    assert SHORT_SEASON_TEXT == "2020: 60 games, scaled to 162"
    assert annotations(fig(client, f"/player/{JULES}/war-chart.json")) == []


def test_unknown_player_chart_is_404(client):
    fig(client, "/player/999999/war-chart.json", 404)


def test_chart_json_never_includes_notes(client, test_db_path):
    conn = sqlite3.connect(test_db_path)
    with conn:
        conn.execute("INSERT INTO player_notes (player_id, body) VALUES (?, ?)", (HANK, "secret-note-text"))
    conn.close()
    for url in (f"/player/{HANK}/war-chart.json", f"/compare/war-chart.json?p1={HANK}&p2={MOE}"):
        assert "secret-note-text" not in client.get(url).get_data(as_text=True)


# ---------------------------------------------------------------- compare chart

def test_compare_chart_has_two_distinguishable_lines_and_no_baseline(client):
    f = fig(client, f"/compare/war-chart.json?p1={HANK}&p2={JULES}")
    first, second = f["data"]
    assert first["name"] == f"Hank Baseline ({HANK})"
    assert second["name"] == f"Jules Doubleplay ({JULES})"
    assert (first["line"]["dash"], first["marker"]["symbol"]) == ("solid", "circle")
    assert (second["line"]["dash"], second["marker"]["symbol"]) == ("dot", "square")
    assert second["line"]["color"] == "#D55E00"
    assert "Hank Baseline" in f["layout"]["title"]["text"] and "Jules Doubleplay" in f["layout"]["title"]["text"]
    assert SHORT_SEASON_TEXT in annotations(f)    # Hank's range reaches 2020


@pytest.mark.parametrize("query, status", [
    ("", 400),
    (f"p1={HANK}", 400),                  # the JSON endpoint has no picker
    (f"p1={HANK}&p2={HANK}", 400),
    (f"p1=0&p2={HANK}", 400),
    (f"p1=abc&p2={HANK}", 400),
    (f"p1={HANK}&p2=999999", 404),
])
def test_compare_chart_validation(client, query, status):
    assert client.get("/compare/war-chart.json?" + query).status_code == status


# ---------------------------------------------------------------- vendored assets

def test_plotly_js_is_served_same_origin(client):
    resp = client.get("/vendor/plotly.min.js")
    assert resp.status_code == 200
    assert resp.mimetype == "application/javascript"
    assert "max-age=31536000" in resp.headers["Cache-Control"]
    assert resp.get_data(as_text=True) == get_plotlyjs()


def test_plotly_css_replaces_the_injected_style(client):
    resp = client.get("/vendor/plotly.css")
    assert resp.status_code == 200 and resp.mimetype == "text/css"
    css = resp.get_data(as_text=True)
    assert ".js-plotly-plot .plotly .main-svg{position:absolute;" in css
    assert ".plotly-notifier{" in css


def test_bundle_extraction_still_matches_this_plotly_version():
    """Fails loudly after a plotly upgrade that changes the bundle's shape."""
    js = get_plotlyjs()
    assert len(plotly_css_from_bundle(js).splitlines()) > 40
    style_id, css = maplibre_css_from_bundle(js)
    assert style_id and f'document.getElementById("{style_id}")' in js
    assert css.startswith(".maplibregl-map{")


def test_chart_page_links_maplibre_css_under_its_style_id(client):
    style_id, _ = maplibre_css_from_bundle(get_plotlyjs())
    body = client.get(f"/player/{HANK}").get_data(as_text=True)
    assert f'<link id="{style_id}" rel="stylesheet"' in body
    assert client.get("/vendor/maplibre.css").mimetype == "text/css"
