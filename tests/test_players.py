"""Player page and player-season page. Fixture rows are in tests/conftest.py."""
import re
import sqlite3

import pytest

from app import CSP
from app.formatting import dec, ip_from_outs, ordinal, rate3, signed

HANK, IVAN, JULES, KURT, LOU, MOE, NED, OTTO = range(900010, 900018)


def page(client, url, status=200):
    resp = client.get(url)
    assert resp.status_code == status, url
    return resp.get_data(as_text=True)


def total_cell(body, key):
    match = re.search(r'data-total="' + key + r'">([^<]*)', body)
    assert match, key
    return match.group(1)


def add_note(db_path, player_id, body, created_at, category="general"):
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute(
            "INSERT INTO player_notes (player_id, category, body, created_at) VALUES (?, ?, ?, ?)",
            (player_id, category, body, created_at),
        )
    conn.close()


# ---------------------------------------------------------------- player page

def test_unknown_player_is_404(client):
    body = page(client, "/player/999999", 404)
    assert "There is no player with ID 999999." in body
    assert "Traceback" not in body


def test_header_shows_id_birth_and_bio(client):
    body = page(client, f"/player/{HANK}")
    assert "Hank Baseline" in body
    assert f'Player ID <span class="mono">{HANK}</span>' in body
    assert "Born 1991-05-05" in body
    assert "Bats R / Throws R" in body
    assert "MLB debut 2014" in body


def test_debut_year_hidden_when_null(client):
    assert "MLB debut" not in page(client, f"/player/{JULES}")


def test_duplicate_names_show_distinct_ids(client):
    a = page(client, "/player/900001")
    b = page(client, "/player/900002")
    assert "Testy McFakerson" in a and "Testy McFakerson" in b
    assert 'Player ID <span class="mono">900001</span>' in a and "Born 1990-04-01" in a
    assert 'Player ID <span class="mono">900002</span>' in b and "Born 1996-11-15" in b


def test_two_way_player_shows_both_tables(client):
    body = page(client, f"/player/{OTTO}")
    assert "<h2>Batting</h2>" in body and "<h2>Pitching</h2>" in body


def test_only_tables_with_rows_are_shown(client):
    hitter = page(client, f"/player/{HANK}")
    pitcher = page(client, f"/player/{MOE}")
    assert "<h2>Batting</h2>" in hitter and "<h2>Pitching</h2>" not in hitter
    assert "<h2>Pitching</h2>" in pitcher and "<h2>Batting</h2>" not in pitcher


def test_zero_pa_batting_rows_are_not_listed(client):
    # 900002's only batting row has 0 PA (a pitcher's placeholder row)
    body = page(client, "/player/900002")
    assert "<h2>Batting</h2>" not in body and "<h2>Pitching</h2>" in body


def test_batting_totals_recompute_rates_from_components(client):
    body = page(client, f"/player/{HANK}")
    # 506 H / 1800 AB; the mean of the four season AVGs would be .285
    assert total_cell(body, "avg") == ".281"
    # (506 + 165 + 17) / (1800 + 165 + 17 + 18) = 688 / 2000
    assert total_cell(body, "obp") == ".344"
    # (506 + 93 + 2*6 + 3*71) / 1800 = 824 / 1800
    assert total_cell(body, "slg") == ".458"
    tfoot = body[body.index("<tfoot>"):body.index("</tfoot>")]
    assert "2015&ndash;2025 totals" in tfoot and "career" not in tfoot.lower()
    assert ">495<" in tfoot and ">2,000<" in tfoot and ">11.0<" in tfoot   # G, PA, WAR


def test_pitching_totals_recompute_rates_from_components(client):
    body = page(client, f"/player/{MOE}")
    # 27 * 150 ER / 1320 outs = 3.068; the mean of the season ERAs would be 3.05
    assert total_cell(body, "era") == "3.07"
    assert total_cell(body, "whip") == "1.17"          # 3 * (110 + 405) / 1320
    assert total_cell(body, "k_per_9") == "9.00"       # 27 * 440 / 1320
    tfoot = body[body.index("<tfoot>"):body.index("</tfoot>")]
    assert ">440.0<" in tfoot                          # IP from summed outs
    assert ">8.6<" in tfoot                            # WAR 4.0 + 3.2 + 1.4


@pytest.mark.parametrize("player_id, keys", [
    (HANK, ["woba", "wrc_plus"]),
    (MOE, ["fip", "xfip", "era_minus"]),
])
def test_context_metric_totals_are_dashes(client, player_id, keys):
    body = page(client, f"/player/{player_id}")
    for key in keys:
        assert total_cell(body, key) == "—"
    assert "league- and park-weighted" in body


def test_season_rows_link_and_mark_2020_and_multi_team(client):
    body = page(client, f"/player/{HANK}")
    assert f'href="/player/{HANK}/season/2015"' in body
    assert '2020</a><span class="fn-mark">*</span>' in body
    assert "2020: 60-game season" in body
    assert 'Multiple<span class="fn-mark">&dagger;</span>' in body
    assert "one combined row" in body
    assert 'href="/team/TSA?season=2015">TSA</a>' in body


def test_ip_uses_display_notation_per_season(client):
    conn_body = page(client, f"/player/{OTTO}")
    assert ">163.1<" in conn_body     # 490 outs


def test_null_stats_render_as_dashes_without_errors(client):
    body = page(client, "/player/900001")   # multi-team rows with no stats
    assert "<h2>Batting</h2>" in body
    assert "data-chart-src" not in body   # no WAR anywhere, so no chart


def test_player_page_has_no_write_forms(client):
    body = page(client, f"/player/{HANK}")
    assert 'method="post"' not in body.lower()
    assert "csrf_token" not in body


def test_compare_form_posts_p1_by_get(client):
    body = page(client, f"/player/{HANK}")
    assert 'action="/compare"' in body and 'method="get"' in body
    assert f'<input type="hidden" name="p1" value="{HANK}">' in body
    assert 'name="q"' in body


def test_notes_panel_shows_three_newest_escaped_and_truncated(client, test_db_path):
    add_note(test_db_path, HANK, "oldest note", "2026-01-01T00:00:00Z")
    add_note(test_db_path, HANK, "<script>alert('x')</script>", "2026-01-02T00:00:00Z", "hitting")
    add_note(test_db_path, HANK, "y" * 300, "2026-01-03T00:00:00Z")
    add_note(test_db_path, HANK, "newest note", "2026-01-04T00:00:00Z")
    body = page(client, f"/player/{HANK}")
    assert "Notes <span class=\"count\">(4)</span>" in body
    assert "newest note" in body and "oldest note" not in body
    assert "<script>alert" not in body
    assert "&lt;script&gt;alert(&#39;x&#39;)&lt;/script&gt;" in body
    assert "y" * 300 not in body and "y" * 190 in body          # truncated
    assert f'href="/player/{HANK}/notes"' in body
    assert "2026-01-04" in body


def test_chart_page_links_assets_and_keeps_strict_script_src(client):
    resp = client.get(f"/player/{HANK}")
    body = resp.get_data(as_text=True)
    assert f'data-chart-src="/player/{HANK}/war-chart.json"' in body
    assert 'id="plotly.js-style-global" class="no-inline-styles"' in body
    assert '<script src="/vendor/plotly.min.js?v=' in body
    assert '<script src="/static/js/charts.js" defer></script>' in body
    csp = resp.headers["Content-Security-Policy"]
    assert csp == CSP
    assert "script-src 'self';" in csp and "style-src 'self';" in csp
    assert "unsafe" not in csp


@pytest.mark.parametrize("position_player, expected", [
    (HANK, "qualified hitters listed at SS"),
    (MOE, "relievers will typically sit below this line"),
    (OTTO, "unambiguous set only"),
    (LOU, "unambiguous set only"),
])
def test_chart_caption_explains_the_baseline(client, position_player, expected):
    assert expected in page(client, f"/player/{position_player}")


# ---------------------------------------------------------------- season page

@pytest.mark.parametrize("url, message", [
    (f"/player/{HANK}/season/2019", "2019 is not a season in this database."),
    (f"/player/{JULES}/season/2020", "has no batting or pitching record in 2020"),
    ("/player/999999/season/2015", "There is no player with ID 999999."),
    (f"/player/{HANK}/season/abc", "There's nothing at this address"),
    (f"/player/{HANK}/season/2015.5", "There's nothing at this address"),
])
def test_season_404s(client, url, message):
    body = page(client, url, 404)
    assert message in body
    assert "Traceback" not in body


# Zero-PA rule: a PA = 0 batting row is shown when the player has no pitching
# row that season (Lou 2015, WAR 0.02), hidden when there is one (900002 2017).

def test_zero_pa_row_without_pitching_is_listed_with_dashes(client):
    body = page(client, f"/player/{LOU}")
    row = re.search(r'season/2015">2015</a>.*?</tr>', body, re.S).group(0)
    cells = re.findall(r'<td class="num">([^<]*)</td>', row)
    # G, PA, HR, R, RBI, SB, AVG, OBP, SLG, wOBA, wRC+, WAR
    assert cells == ["1", "0", "0", "0", "0", "0", "—", "—", "—", "—", "—", "0.0"]
    tfoot = body[body.index("<tfoot>"):body.index("</tfoot>")]
    assert total_cell(body, "avg") == ".222"            # 10 H / 45 AB, unchanged by the 0-AB row
    assert ">0.1<" in tfoot                             # WAR 0.02 + 0.1


def test_zero_pa_row_without_pitching_has_a_season_page(client):
    text = re.sub(r"\s+", " ", page(client, f"/player/{LOU}/season/2015"))
    assert "<dt>PA</dt><dd>0</dd>" in text
    assert "<dt>wOBA</dt><dd>—</dd>" in text           # stored 0, shown as missing
    assert "<dt>AVG</dt><dd>—</dd>" in text
    assert "<dt>Def</dt><dd>+0.2</dd>" in text
    assert "Not a qualified hitter in 2015" in text


def test_pitchers_zero_pa_row_stays_hidden(client):
    body = page(client, "/player/900002/season/2017")
    assert "<h2>Pitching" in body and "<h2>Batting" not in body
    assert "season/2017\">2017</a>" in page(client, "/player/900002")   # pitching table only
    assert "<h2>Batting</h2>" not in page(client, "/player/900002")


def test_qualified_hitter_ranks(client):
    body = page(client, f"/player/{HANK}/season/2015")
    text = re.sub(r"\s+", " ", body)
    assert "wOBA</span> 3rd of 9 qualified hitters" in text
    assert "wRC+</span> tied 3rd of 9 qualified hitters" in text
    assert "WAR</span> 2nd of 9 qualified hitters" in text


def test_qualified_pitcher_ranks_ascending_for_era_minus_and_fip(client):
    text = re.sub(r"\s+", " ", page(client, f"/player/{MOE}/season/2016"))
    assert "ERA-</span> 2nd of 9 qualified pitchers" in text
    assert "FIP</span> 2nd of 9 qualified pitchers" in text
    assert "WAR</span> 1st of 9 qualified pitchers" in text


def test_unqualified_hitter_shows_threshold(client):
    text = re.sub(r"\s+", " ", page(client, f"/player/{IVAN}/season/2016"))
    assert "Not a qualified hitter in 2016" in text
    assert "503 PA" in text and "Ivan Rangefactor had 300" in text
    assert "qualified hitters" not in text


def test_unqualified_pitcher_shows_threshold(client):
    text = re.sub(r"\s+", " ", page(client, f"/player/{NED}/season/2015"))
    assert "Not a qualified pitcher in 2015" in text
    assert "162.0 IP" in text and "threw 66.2" in text


def test_2020_threshold_scales(client):
    text = re.sub(r"\s+", " ", page(client, f"/player/{HANK}/season/2020"))
    assert "60-game season. Counting stats are not scaled here." in text
    assert "wOBA</span> 1st of 5 qualified hitters" in text   # 200 PA >= 3.1 * 60


def test_multi_team_banner(client):
    body = page(client, f"/player/{HANK}/season/2017")
    assert "Played for more than one team this season" in body
    assert "Multiple teams" in body
    assert "60-game season" not in body


def test_full_rows_and_two_way_season(client):
    text = re.sub(r"\s+", " ", page(client, f"/player/{OTTO}/season/2016"))
    for label in ("2B", "3B", "BB%", "K%", "ISO", "OPS", "Off", "Def", "BsR",
                  "BB/9", "HR/9", "K/BB", "LOB%", "BABIP", "FIP-", "ERA+"):
        assert f"<dt>{label}</dt>" in text, label
    assert "<dd>163.1</dd>" in text          # ip_display
    assert "<dd>75.0%</dd>" in text          # LOB% stored as a fraction
    assert "<dd>.280</dd>" in text           # BABIP
    assert "Not a qualified hitter in 2016" in text     # 450 PA
    assert "1st of 9 qualified pitchers" in text        # ERA- 88 leads 2016


# ---------------------------------------------------------------- filters

def test_filters():
    assert rate3(0.28111) == ".281" and rate3(1.1111) == "1.111" and rate3(None) == "—"
    assert dec(-0.04, 1) == "0.0" and dec(3.0681, 2) == "3.07" and signed(-0.04) == "+0.0"
    assert ip_from_outs(1320) == "440.0" and ip_from_outs(541) == "180.1"
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 111, 112)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "111th", "112th"]


HIDDEN_NOTE = "Baseline hidden in seasons with fewer than 5 other qualified players at the position."


@pytest.mark.parametrize("player_id, shown", [(HANK, True), (MOE, True), (OTTO, False), (LOU, False)])
def test_caption_states_leave_one_out_and_minimum(client, player_id, shown):
    text = re.sub(r"\s+", " ", page(client, f"/player/{player_id}"))
    assert (HIDDEN_NOTE in text) is shown
    assert ("own season is left out" in text) is shown
