import pytest

from app import notes as notes_module
from tests.conftest import csrf_token, query_db

PLAYER = 900001
LIST_URL = f"/player/{PLAYER}/notes"


def note_rows(db_path):
    return query_db(db_path, "SELECT note_id, player_id, category, body, created_at, updated_at "
                             "FROM player_notes ORDER BY note_id")


def add_note(client, body="Plus arm, below-average range.", category="defense", player_id=PLAYER):
    url = f"/player/{player_id}/notes"
    token = csrf_token(client, LIST_URL)
    return client.post(url, data={"csrf_token": token, "category": category, "body": body})


# ---------------------------------------------------------------- create / list

def test_list_page_shows_header_and_form(client):
    resp = client.get(LIST_URL)
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Testy McFakerson" in body and "900001" in body and "SS" in body
    assert 'name="csrf_token"' in body
    for cat in notes_module.CATEGORIES:
        assert f'value="{cat}"' in body


def test_create_redirects_and_note_appears(client, test_db_path):
    resp = add_note(client, body="Line one\nLine two")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(LIST_URL)

    page = client.get(LIST_URL).get_data(as_text=True)
    assert "Note added." in page                      # flash survived the redirect
    assert "Line one\nLine two" in page               # newlines kept, no <br> injected
    rows = note_rows(test_db_path)
    assert len(rows) == 1
    note_id, player_id, category, body, created_at, updated_at = rows[0]
    assert (player_id, category, body, updated_at) == (PLAYER, "defense", "Line one\nLine two", None)
    assert created_at.endswith("Z")


def test_crlf_is_normalized_and_body_stripped(client, test_db_path):
    add_note(client, body="  first\r\nsecond  \r\n")
    assert note_rows(test_db_path)[0][3] == "first\nsecond"


def test_notes_listed_newest_first(client, test_db_path):
    add_note(client, body="older")
    add_note(client, body="newer")
    page = client.get(LIST_URL).get_data(as_text=True)
    assert page.index("newer") < page.index("older")


def test_notes_are_per_player(client):
    add_note(client, body="only for 900001")
    assert "only for 900001" not in client.get("/player/900002/notes").get_data(as_text=True)


def test_post_without_csrf_token_is_400_and_writes_nothing(client, test_db_path):
    resp = client.post(LIST_URL, data={"category": "general", "body": "no token"})
    body = resp.get_data(as_text=True)
    assert resp.status_code == 400
    assert "nothing was saved" in body
    assert note_rows(test_db_path) == []


def test_post_with_bad_csrf_token_is_400(client, test_db_path):
    csrf_token(client, LIST_URL)   # establish a session
    resp = client.post(LIST_URL, data={"csrf_token": "forged", "category": "general", "body": "x"})
    assert resp.status_code == 400
    assert note_rows(test_db_path) == []


def test_script_body_is_stored_raw_and_rendered_escaped(client, test_db_path):
    payload = "<script>alert(1)</script>"
    add_note(client, body=payload)
    assert note_rows(test_db_path)[0][3] == payload
    page = client.get(LIST_URL).get_data(as_text=True)
    assert payload not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


@pytest.mark.parametrize("body, category", [
    ("", "general"),
    ("   \n\t  ", "general"),
    ("x" * 2001, "general"),
    ("fine body", "scouting"),          # not one of the 5 CHECK values
    ("fine body", ""),
])
def test_invalid_input_rerenders_400_and_writes_nothing(client, test_db_path, body, category):
    resp = add_note(client, body=body, category=category)
    page = resp.get_data(as_text=True)
    assert resp.status_code == 400
    assert 'class="field-error"' in page
    assert note_rows(test_db_path) == []


def test_body_length_boundaries(client, test_db_path):
    assert add_note(client, body="x").status_code == 302
    assert add_note(client, body="y" * 2000).status_code == 302
    assert [len(r[3]) for r in note_rows(test_db_path)] == [1, 2000]


def test_nonexistent_player_is_404_and_writes_nothing(client, test_db_path):
    assert client.get("/player/999999/notes").status_code == 404
    resp = add_note(client, player_id=999999)
    assert resp.status_code == 404
    assert note_rows(test_db_path) == []


# ---------------------------------------------------------------- edit / delete

def test_edit_changes_body_category_and_updated_at(client, test_db_path):
    add_note(client, body="original", category="hitting")
    note_id = note_rows(test_db_path)[0][0]
    edit_url = f"/notes/{note_id}/edit"

    form_page = client.get(edit_url).get_data(as_text=True)
    assert "original" in form_page
    token = csrf_token(client, edit_url)
    resp = client.post(edit_url, data={"csrf_token": token, "category": "pitching", "body": "revised"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith(LIST_URL)

    _, _, category, body, created_at, updated_at = note_rows(test_db_path)[0]
    assert (category, body) == ("pitching", "revised")
    assert updated_at is not None and updated_at >= created_at
    assert "edited" in client.get(LIST_URL).get_data(as_text=True)


def test_invalid_edit_is_400_and_keeps_original(client, test_db_path):
    add_note(client, body="original")
    note_id = note_rows(test_db_path)[0][0]
    edit_url = f"/notes/{note_id}/edit"
    token = csrf_token(client, edit_url)
    resp = client.post(edit_url, data={"csrf_token": token, "category": "general", "body": "   "})
    assert resp.status_code == 400
    assert note_rows(test_db_path)[0][3] == "original"
    assert note_rows(test_db_path)[0][5] is None


def test_edit_post_without_body_field_is_rejected(client, test_db_path):
    add_note(client, body="original")
    note_id = note_rows(test_db_path)[0][0]
    edit_url = f"/notes/{note_id}/edit"
    token = csrf_token(client, edit_url)
    resp = client.post(edit_url, data={"csrf_token": token, "category": "general"})
    assert resp.status_code == 400
    assert note_rows(test_db_path)[0][5] is None


def test_delete_removes_row(client, test_db_path):
    add_note(client, body="to delete")
    note_id = note_rows(test_db_path)[0][0]
    token = csrf_token(client, LIST_URL)
    resp = client.post(f"/notes/{note_id}/delete", data={"csrf_token": token})
    assert resp.status_code == 302
    assert note_rows(test_db_path) == []
    assert "Note deleted." in client.get(LIST_URL).get_data(as_text=True)


def test_deleted_newest_note_id_is_not_reused(client, test_db_path):
    add_note(client, body="first")
    add_note(client, body="second")
    newest = max(r[0] for r in note_rows(test_db_path))
    token = csrf_token(client, LIST_URL)
    assert client.post(f"/notes/{newest}/delete", data={"csrf_token": token}).status_code == 302

    add_note(client, body="third")
    ids = [r[0] for r in note_rows(test_db_path)]
    assert newest not in ids
    assert max(ids) == newest + 1


def test_delete_without_csrf_token_is_400(client, test_db_path):
    add_note(client, body="keep me")
    note_id = note_rows(test_db_path)[0][0]
    assert client.post(f"/notes/{note_id}/delete").status_code == 400
    assert len(note_rows(test_db_path)) == 1


def test_missing_note_edit_and_delete_are_404(client):
    token = csrf_token(client, LIST_URL)
    assert client.get("/notes/424242/edit").status_code == 404
    assert client.post("/notes/424242/edit",
                       data={"csrf_token": token, "category": "general", "body": "x"}).status_code == 404
    assert client.post("/notes/424242/delete", data={"csrf_token": token}).status_code == 404


def test_get_on_delete_is_405(client, test_db_path):
    add_note(client, body="safe")
    note_id = note_rows(test_db_path)[0][0]
    resp = client.get(f"/notes/{note_id}/delete")
    assert resp.status_code == 405
    assert "POST" in resp.headers["Allow"]
    assert "Traceback" not in resp.get_data(as_text=True)
    assert len(note_rows(test_db_path)) == 1


# ---------------------------------------------------------------- connection discipline

def test_get_routes_never_open_the_rw_connection(client, monkeypatch):
    add_note(client, body="exists")

    def forbidden():
        raise AssertionError("GET handler opened get_rw_db()")

    monkeypatch.setattr(notes_module, "get_rw_db", forbidden)
    assert client.get(LIST_URL).status_code == 200
    assert client.get("/notes/1/edit").status_code == 200


def test_search_results_link_to_notes(client):
    body = client.get("/", query_string={"q": "mcfakerson"}).get_data(as_text=True)
    assert 'href="/player/900001/notes"' in body
