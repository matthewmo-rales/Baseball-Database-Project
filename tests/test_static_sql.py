"""Static check: no SQL text in app/ is built from runtime data.

Every .execute / .executemany / .executescript call in app/ must pass, as its
first argument, a static SQL expression:
  - a string literal,
  - a module-level constant assigned once to a static SQL expression, or
  - '+' concatenation of those (fixed at import time).
f-strings, '%', .format() and any other call or name fail.

The one other path is the saved-query registry: queries.execute(db, <x>.sql,
params), whose SQL is parsed from queries/analysis.sql at startup. Inside
queries.execute() itself, db.execute(sql, ...) is the single allowlisted
exception; it must carry a 'static-sql-allow:' comment and be named below.
"""
import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"
EXECUTE_METHODS = {"execute", "executemany", "executescript"}

# (file relative to app/, enclosing function) -> why it is allowed
ALLOWLIST = {
    ("queries.py", "execute"): "runs registry SQL parsed from queries/analysis.sql at startup",
}


def _module_constants(tree):
    """Names assigned exactly once at module level to a static SQL expression."""
    counts, values = {}, {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            counts[name] = counts.get(name, 0) + 1
            values[name] = node.value
    consts = set()
    for node in tree.body:          # in order, so a constant may build on earlier ones
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if counts[name] == 1 and _is_static(values[name], consts):
                consts.add(name)
    return consts


def _is_static(node, consts):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return True
    if isinstance(node, ast.Name):
        return node.id in consts
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _is_static(node.left, consts) and _is_static(node.right, consts)
    return False        # JoinedStr (f-string), BinOp Mod (%), Call (.format etc.), anything else


def _enclosing_functions(tree):
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def _function_of(node, parents):
    while node in parents:
        node = parents[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node.name
    return None


def collect_call_sites():
    """[(file, line, function, kind, ok, detail)] for every execute-family call."""
    sites = []
    for path in sorted(APP.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source)
        consts = _module_constants(tree)
        parents = _enclosing_functions(tree)
        rel = path.relative_to(APP).as_posix()
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in EXECUTE_METHODS):
                continue
            func = _function_of(node, parents)
            receiver = node.func.value
            if isinstance(receiver, ast.Name) and receiver.id == "queries":
                # registry path: queries.execute(db, <query>.sql, params)
                sql = node.args[1] if len(node.args) > 1 else None
                ok = isinstance(sql, ast.Attribute) and sql.attr == "sql"
                sites.append((rel, node.lineno, func, "registry", ok, ast.unparse(sql) if sql else ""))
                continue
            first = node.args[0] if node.args else None
            if first is not None and _is_static(first, consts):
                sites.append((rel, node.lineno, func, "static", True, ast.unparse(first)[:60]))
                continue
            allowed = (rel, func) in ALLOWLIST and "static-sql-allow:" in lines[node.lineno - 1]
            sites.append((rel, node.lineno, func, "allowlisted" if allowed else "DYNAMIC", allowed,
                          ast.unparse(first) if first is not None else ""))
    return sites


def test_every_execute_call_uses_static_sql():
    bad = [s for s in collect_call_sites() if not s[4]]
    assert not bad, "SQL built at runtime:\n" + "\n".join(f"{f}:{l} in {fn}(): {d}" for f, l, fn, _k, _o, d in bad)


def test_allowlist_entries_are_used():
    used = {(f, fn) for f, _l, fn, kind, _o, _d in collect_call_sites() if kind == "allowlisted"}
    assert used == set(ALLOWLIST)


def test_call_sites_were_found():
    kinds = {site[3] for site in collect_call_sites()}
    assert {"static", "registry", "allowlisted"} <= kinds


@pytest.mark.parametrize("snippet, expected", [
    ('db.execute("SELECT 1")', True),
    ('X = "SELECT 1"\ndb.execute(X)', True),
    ('X = "SELECT "\nY = X + "1"\ndb.execute(Y + " -- ok")', True),
    ('db.execute(f"SELECT {x}")', False),
    ('db.execute("SELECT %s" % x)', False),
    ('db.execute("SELECT {}".format(x))', False),
    ('db.execute("SELECT " + x)', False),
    ('X = "a"\nX = "b"\ndb.execute(X)', False),          # reassigned: not a constant
    ('def f(sql):\n    db.execute(sql)', False),
    ('X = "SELECT " + str(1)\ndb.execute(X)', False),
])
def test_checker_itself(snippet, expected):
    tree = ast.parse(snippet)
    consts = _module_constants(tree)
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "execute")
    assert _is_static(call.args[0], consts) is expected
