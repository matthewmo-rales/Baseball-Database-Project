"""Jinja filters for stat display. Every filter renders None as an em dash."""
DASH = "—"


def rate3(value):
    """.283 style: three decimals, no leading zero below 1."""
    if value is None:
        return DASH
    text = f"{value:.3f}"
    if text.startswith("0."):
        return text[1:]
    return text


def _round(value, places):
    # + 0.0 turns -0.0 into 0.0, so -0.04 shows as 0.0, not -0.0
    return round(value, places) + 0.0


def dec(value, places=2):
    if value is None:
        return DASH
    return f"{_round(value, places):.{places}f}"


def signed(value, places=1):
    if value is None:
        return DASH
    return f"{_round(value, places):+.{places}f}"


def num(value):
    if value is None:
        return DASH
    return f"{value:,}" if isinstance(value, int) else f"{value:,.0f}"


def pct(value, places=1, fraction=False):
    """Percent with a % sign. fraction=True for values stored as 0-1 (LOB%)."""
    if value is None:
        return DASH
    return f"{value * 100 if fraction else value:.{places}f}%"


def ip_from_outs(outs):
    """Summed outs in baseball innings notation: 1320 -> 440.0, 541 -> 180.1."""
    if outs is None:
        return DASH
    return f"{outs // 3}.{outs % 3}"


def ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def init_app(app):
    app.jinja_env.filters.update(
        rate3=rate3, dec=dec, signed=signed, num=num, pct=pct,
        ip_from_outs=ip_from_outs, ordinal=ordinal,
    )
