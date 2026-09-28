"""Blueprint "notes": CRUD on player_notes, the app's only writable relation.

Reads (including every GET) use get_ro_db(). Only the POST handlers use
get_rw_db(), whose authorizer allows writes to player_notes and nothing else.
"""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_wtf import FlaskForm
from wtforms import SelectField, TextAreaField
from wtforms.validators import DataRequired, Length

from .db import get_ro_db, get_rw_db

bp = Blueprint("notes", __name__)

# Must match the CHECK on player_notes.category in design/schema.sql.
CATEGORIES = ("hitting", "pitching", "defense", "baserunning", "general")
BODY_MAX = 2000

def clean_body(value):
    """Normalize browser CRLF to LF, then strip, so length matches what's stored."""
    if value is None:
        return value
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


class NoteForm(FlaskForm):
    # The server-side checks mirror the DB CHECKs: the form gives the friendly
    # error, the constraint is the backstop.
    category = SelectField(
        "Category",
        choices=[(c, c.capitalize()) for c in CATEGORIES],
        default="general",
    )
    body = TextAreaField(
        "Note",
        filters=[clean_body],
        validators=[
            DataRequired(message="Write something before saving."),
            Length(min=1, max=BODY_MAX, message=f"Notes are limited to {BODY_MAX:,} characters."),
        ],
    )


def _player_or_404(player_id):
    player = get_ro_db().execute(
        "SELECT player_id, full_name, primary_position FROM players WHERE player_id = ?",
        (player_id,),
    ).fetchone()
    if player is None:
        abort(404)
    return player


def _note_or_404(note_id):
    note = get_ro_db().execute(
        """SELECT n.note_id, n.player_id, n.category, n.body, n.created_at, n.updated_at,
                  p.full_name, p.primary_position
             FROM player_notes n
             JOIN players p ON p.player_id = n.player_id
            WHERE n.note_id = ?""",
        (note_id,),
    ).fetchone()
    if note is None:
        abort(404)
    return note


def _render_list(player, form, status=200):
    notes = get_ro_db().execute(
        """SELECT note_id, category, body, created_at, updated_at
             FROM player_notes
            WHERE player_id = ?
            ORDER BY created_at DESC, note_id DESC""",
        (player["player_id"],),
    ).fetchall()
    return render_template(
        "notes/list.html", player=player, notes=notes, form=form, body_max=BODY_MAX
    ), status


@bp.route("/player/<int:player_id>/notes", methods=["GET", "POST"])
def list_notes(player_id):
    player = _player_or_404(player_id)
    form = NoteForm()
    if not form.is_submitted():
        return _render_list(player, form)
    if not form.validate():
        return _render_list(player, form, 400)

    db = get_rw_db()
    with db:
        db.execute(
            "INSERT INTO player_notes (player_id, category, body) VALUES (?, ?, ?)",
            (player_id, form.category.data, form.body.data),
        )
    flash("Note added.")
    return redirect(url_for("notes.list_notes", player_id=player_id))


@bp.route("/notes/<int:note_id>/edit", methods=["GET", "POST"])
def edit_note(note_id):
    note = _note_or_404(note_id)
    if request.method == "GET":
        form = NoteForm(data={"category": note["category"], "body": note["body"]})
    else:
        # POST binds only the submitted data; prefilling here would let a
        # request that omits `body` silently keep the old text.
        form = NoteForm()
    if not form.is_submitted():
        return render_template("notes/edit.html", note=note, form=form, body_max=BODY_MAX)
    if not form.validate():
        return render_template("notes/edit.html", note=note, form=form, body_max=BODY_MAX), 400

    db = get_rw_db()
    with db:
        cur = db.execute(
            """UPDATE player_notes
                  SET category = ?, body = ?,
                      updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                WHERE note_id = ?""",
            (form.category.data, form.body.data, note_id),
        )
    if cur.rowcount == 0:       # deleted between the read and the write
        abort(404)
    flash("Note updated.")
    return redirect(url_for("notes.list_notes", player_id=note["player_id"]))


@bp.route("/notes/<int:note_id>/delete", methods=["POST"])
def delete_note(note_id):
    note = _note_or_404(note_id)
    db = get_rw_db()
    with db:
        cur = db.execute("DELETE FROM player_notes WHERE note_id = ?", (note_id,))
    if cur.rowcount == 0:
        abort(404)
    flash("Note deleted.")
    return redirect(url_for("notes.list_notes", player_id=note["player_id"]))
