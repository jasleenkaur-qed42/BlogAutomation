"""Topic-specific illustrations (banner, ui_screen, cards) drawn from a small writer-authored spec with matplotlib.

The writer describes *what* to show; this module owns the look, so output is deterministic and offline.
UI screens are illustrations of a typical screen, never real screenshots; icons are generic stylised marks."""
import textwrap

SCENE_TYPES = ("banner", "ui_screen", "cards")
ICONS = ("flame", "atom", "plus", "phone", "cloud", "database", "lock", "gear", "check", "user", "code", "bolt",
         "server", "search", "web")
W = 1200
MAX_TEXT = 90


def _text(v, hi=MAX_TEXT):
    return isinstance(v, (str, int, float)) and not isinstance(v, bool) and 0 < len(str(v).strip()) <= hi


def _items(v, lo, hi):
    return isinstance(v, list) and lo <= len(v) <= hi


def scene_error(spec):
    """Return a message if `spec` (type banner | ui_screen | cards) is invalid, else None."""
    t = spec["type"]
    if t == "banner":
        tiles = spec.get("tiles")
        if not _items(tiles, 1, 3):
            return "banner needs tiles: a list of 1-3 {label, icon}"
        for x in tiles:
            if not (isinstance(x, dict) and _text(x.get("label"), 24) and x.get("icon") in ICONS):
                return f"each tile needs a label (max 24 chars) and an icon from {', '.join(ICONS)}"
        if spec.get("subtitle") is not None and not _text(spec["subtitle"]):
            return "subtitle must be short text"
    elif t == "ui_screen":
        if not _text(spec.get("heading"), 40):
            return "ui_screen needs a heading (max 40 chars)"
        for key, hi, n in (("sidebar", 8, 24), ("steps", 4, 30)):
            v = spec.get(key, [])
            if not (_items(v, 0, hi) and all(_text(x, n) for x in v)):
                return f"{key} must be a list of up to {hi} short labels"
        opts = spec.get("options", [])
        if not (_items(opts, 0, 4) and all(isinstance(o, dict) and _text(o.get("label"), 40)
                                           and (o.get("detail") is None or _text(o["detail"], 140)) for o in opts)):
            return "options must be up to 4 {label, detail?} items"
        if spec.get("selected") is not None and spec["selected"] not in [o["label"] for o in opts]:
            return "selected must match an option label"
        if not (spec.get("sidebar") or opts or spec.get("code")):
            return "ui_screen needs a sidebar, options or code"
        for key, hi in (("app", 30), ("active", 24), ("callout", 140), ("button", 20)):
            if spec.get(key) is not None and not _text(spec[key], hi):
                return f"{key} must be short text (max {hi} chars)"
        code = spec.get("code")
        if code is not None and not (isinstance(code, str) and code.strip() and len(code.splitlines()) <= 8
                                     and all(len(x) <= 70 for x in code.splitlines())):
            return "code must be 1-8 lines of at most 70 chars"
    else:
        cards = spec.get("cards")
        if not _items(cards, 2, 6):
            return "cards needs a list of 2-6 {title, subtitle?, icon?}"
        for c in cards:
            if not (isinstance(c, dict) and _text(c.get("title"), 22) and (c.get("subtitle") is None or _text(c["subtitle"], 40))
                    and c.get("icon", "plus") in ICONS):
                return f"each card needs a title (max 22 chars) and an optional icon from {', '.join(ICONS)}"
    return None


# ---- drawing helpers (pixel coordinates, y grows downward) ----
def _icon(ax, name, cx, cy, r, color):
    """Draw an icon above everything already on the canvas."""
    n_p, n_l = len(ax.patches), len(ax.lines)
    _draw_icon(ax, name, cx, cy, r, color)
    for a in ax.patches[n_p:] + ax.lines[n_l:]:
        a.set_zorder(6)


def _draw_icon(ax, name, cx, cy, r, color):
    from matplotlib.patches import Circle, Ellipse, FancyBboxPatch, Polygon, Rectangle
    P = lambda pts: Polygon([(cx + x * r, cy + y * r) for x, y in pts], closed=True, fc=color, ec="none")  # noqa: E731
    if name == "flame":
        ax.add_patch(P([(-.8, .9), (-.9, -.2), (-.4, -.9), (-.1, -.2), (.15, -.6), (.9, .9)]))
        ax.add_patch(Polygon([(cx + x * r, cy + y * r) for x, y in [(-.8, .9), (-.35, .1), (.15, -.6), (.9, .9)]],
                             closed=True, fc="#FFCA28", ec="none"))
        ax.add_patch(Polygon([(cx + x * r, cy + y * r) for x, y in [(-.8, .9), (-.35, .1), (.2, .9)]],
                             closed=True, fc="#F57C00", ec="none"))
    elif name == "atom":
        for ang in (0, 60, 120):
            ax.add_patch(Ellipse((cx, cy), 2 * r, 0.75 * r, angle=ang, fc="none", ec=color, lw=r * 0.09 * 2.2))
        ax.add_patch(Circle((cx, cy), r * 0.18, fc=color, ec="none"))
    elif name == "plus":
        ax.add_patch(Rectangle((cx - r * .8, cy - r * .12), r * 1.6, r * .24, fc=color, ec="none"))
        ax.add_patch(Rectangle((cx - r * .12, cy - r * .8), r * .24, r * 1.6, fc=color, ec="none"))
    elif name == "phone":
        ax.add_patch(FancyBboxPatch((cx - r * .45, cy - r), r * .9, r * 2, boxstyle="round,pad=0,rounding_size=%f" % (r * .15),
                                    fc="none", ec=color, lw=r * .2))
        ax.add_patch(Circle((cx, cy + r * .72), r * .07, fc=color, ec="none"))
    elif name == "cloud":
        for dx, dy, rr in ((-.45, .1, .4), (0, -.2, .55), (.5, .1, .4)):
            ax.add_patch(Circle((cx + dx * r, cy + dy * r), rr * r, fc=color, ec="none"))
        ax.add_patch(Rectangle((cx - .45 * r, cy + .1 * r), .95 * r, .4 * r, fc=color, ec="none"))
    elif name in ("database", "server"):
        for i in range(3):
            ax.add_patch(FancyBboxPatch((cx - r * .8, cy - r * .85 + i * r * .62), r * 1.6, r * .5,
                                        boxstyle="round,pad=0,rounding_size=%f" % (r * .12), fc=color, ec="none"))
    elif name == "lock":
        ax.add_patch(Ellipse((cx, cy - r * .3), r * 1, r * 1.1, fc="none", ec=color, lw=r * .2))
        ax.add_patch(FancyBboxPatch((cx - r * .65, cy - r * .1), r * 1.3, r * .95, boxstyle="round,pad=0,rounding_size=%f" % (r * .12),
                                    fc=color, ec="none"))
    elif name == "gear":
        for ang in range(0, 180, 45):
            ax.add_patch(Rectangle((cx - r * .12, cy - r), r * .24, r * 2, angle=ang, rotation_point=(cx, cy), fc=color, ec="none"))
        ax.add_patch(Circle((cx, cy), r * .62, fc=color, ec="none"))
        ax.add_patch(Circle((cx, cy), r * .28, fc="white", ec="none"))
    elif name == "check":
        ax.add_patch(Circle((cx, cy), r, fc=color, ec="none"))
        ax.plot([cx - r * .45, cx - r * .1, cx + r * .5], [cy, cy + r * .38, cy - r * .35], color="white", lw=r * .22,
                solid_capstyle="round")
    elif name == "user":
        ax.add_patch(Circle((cx, cy - r * .4), r * .38, fc=color, ec="none"))
        ax.add_patch(Ellipse((cx, cy + r * .75), r * 1.6, r * 1.2, fc=color, ec="none"))
    elif name == "code":
        ax.plot([cx - r * .3, cx - r * .85, cx - r * .3], [cy - r * .55, cy, cy + r * .55], color=color, lw=r * .2, solid_capstyle="round")
        ax.plot([cx + r * .3, cx + r * .85, cx + r * .3], [cy - r * .55, cy, cy + r * .55], color=color, lw=r * .2, solid_capstyle="round")
    elif name == "bolt":
        ax.add_patch(P([(.2, -1), (-.6, .15), (-.05, .15), (-.25, 1), (.65, -.2), (.05, -.2)]))
    elif name == "search":
        ax.add_patch(Circle((cx - r * .2, cy - r * .2), r * .55, fc="none", ec=color, lw=r * .2))
        ax.plot([cx + r * .2, cx + r * .8], [cy + r * .2, cy + r * .8], color=color, lw=r * .26, solid_capstyle="round")
    else:  # web
        ax.add_patch(Circle((cx, cy), r * .85, fc="none", ec=color, lw=r * .14))
        ax.add_patch(Ellipse((cx, cy), r * .8, r * 1.7, fc="none", ec=color, lw=r * .12))
        ax.plot([cx - r * .85, cx + r * .85], [cy, cy], color=color, lw=r * .12)


def _canvas(height):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(W / 100, height / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, W)
    ax.set_ylim(height, 0)
    ax.axis("off")
    return plt, fig, ax


def _gradient(ax, height, c1, c2):
    import numpy as np
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("g", [c1, c2])
    grad = np.linspace(0, 1, 256).reshape(1, -1)
    ax.imshow(grad, extent=(0, W, height, 0), cmap=cmap, aspect="auto", zorder=0)
    ax.set_xlim(0, W)
    ax.set_ylim(height, 0)


def _box(ax, x, y, w, h, fc, ec="none", r=14, lw=1.5, z=1):
    from matplotlib.patches import FancyBboxPatch
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw, zorder=z))


def _t(ax, x, y, s, size, color="#202124", weight="normal", ha="left", va="center", mono=False, z=5):
    ax.text(x, y, str(s), fontsize=size * 0.72, color=color, fontweight=weight, ha=ha, va=va, zorder=z,
            family="monospace" if mono else "DejaVu Sans")


def _banner(spec):
    h = 630
    plt, fig, ax = _canvas(h)
    _gradient(ax, h, "#0D47A1", "#BA68E6")
    tiles = spec["tiles"]
    n = len(tiles)
    step = 1040 / n
    cy = 270
    size = max(24, min(50, int(min(step * 0.9 / (0.62 * len(t["label"])) for t in tiles))))  # no label overlaps its neighbour
    for i, tl in enumerate(tiles):
        cx = 80 + step * (i + 0.5) + 40 if n > 1 else W / 2
        cx = (W - 1040) / 2 + step * (i + 0.5)
        _icon(ax, tl["icon"], cx, cy - 20, 105, "#FFFFFF" if tl["icon"] != "flame" else "#FFA000")
        _t(ax, cx, cy + 160, tl["label"], size, "white", "bold", "center")
        if i < n - 1:
            px = (W - 1040) / 2 + step * (i + 1)
            _icon(ax, "plus", px, cy - 20, 55, "#F5E6D3")
    _t(ax, W / 2, 540, spec["title"], 38, "white", "bold", "center")
    if spec.get("subtitle"):
        _t(ax, W / 2, 592, spec["subtitle"], 26, "#E8EAF6", "normal", "center")
    return fig, plt


def _ui_screen(spec):
    h = 700
    plt, fig, ax = _canvas(h)
    ax.add_patch(plt.Rectangle((0, 0), W, h, fc="#F1F3F4", ec="none", zorder=0))
    ax.add_patch(plt.Rectangle((0, 0), W, 56, fc="white", ec="none", zorder=1))
    for i, c in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
        ax.add_patch(plt.Circle((28 + i * 28, 28), 8, fc=c, ec="none", zorder=2))
    _t(ax, 140, 28, spec.get("app", ""), 24, "#5F6368", "bold")
    side = spec.get("sidebar", [])
    x0 = 0
    if side:
        ax.add_patch(plt.Rectangle((0, 56), 280, h - 56, fc="#263238", ec="none", zorder=1))
        for i, s in enumerate(side):
            y = 110 + i * 62
            on = s == spec.get("active")
            if on:
                ax.add_patch(plt.Rectangle((0, y - 26), 280, 52, fc="#37474F", ec="none", zorder=2))
            _t(ax, 28, y, s, 24, "white" if on else "#B0BEC5", "bold" if on else "normal")
        x0 = 280
    opts, steps, code = spec.get("options", []), spec.get("steps", []), spec.get("code")
    mx, my, mw, mh = x0 + 70, 100, W - x0 - 140, h - 150
    _box(ax, mx + 6, my + 8, mw, mh, "#00000022", r=18, z=2)
    _box(ax, mx, my, mw, mh, "white", "#DADCE0", 18, z=3)
    ax.add_patch(plt.Rectangle((mx, my), mw, 92, fc="#1A73E8", ec="none", zorder=4))
    _t(ax, mx + 30, my + 32, spec["heading"], 32, "white", "bold")
    for i, s in enumerate(steps):
        sx = mx + 30 + i * 330
        ax.add_patch(plt.Circle((sx + 12, my + 70), 12, fc="white" if i == 0 else "#90CAF9", ec="none", zorder=5))
        _t(ax, sx + 12, my + 70, i + 1, 15, "#1A73E8", "bold", "center")
        _t(ax, sx + 34, my + 70, s, 20, "white" if i == 0 else "#E3F2FD")
    y = my + 130
    for o in opts:
        on = o["label"] == spec.get("selected")
        ax.add_patch(plt.Circle((mx + 46, y + 4), 11, fc="white", ec="#1A73E8" if on else "#80868B", lw=2.5, zorder=5))
        if on:
            ax.add_patch(plt.Circle((mx + 46, y + 4), 5, fc="#1A73E8", ec="none", zorder=6))
        _t(ax, mx + 76, y, o["label"], 24, "#202124", "bold")
        if o.get("detail"):
            for j, ln in enumerate(textwrap.wrap(o["detail"], 46)[:3]):
                _t(ax, mx + 76, y + 34 + j * 28, ln, 19, "#5F6368")
        y += 130 if o.get("detail") else 70
    if code:
        cx0 = mx + (mw * 0.5 if opts else 30)
        cw = mw * 0.5 - 30 if opts else mw - 60
        _box(ax, cx0, my + 120, cw, mh - 250, "#F1F3F4", "#DADCE0", 8, z=4)
        for j, ln in enumerate(code.splitlines()):
            _t(ax, cx0 + 18, my + 150 + j * 30, ln, 18, "#3C4043", mono=True)
    if spec.get("callout"):
        _box(ax, mx + 30, my + mh - 150, mw - 60, 64, "#FEF7E0", "#F9AB00", 8, 1, z=4)
        ax.add_patch(plt.Circle((mx + 62, my + mh - 118), 12, fc="#F9AB00", ec="none", zorder=5))
        _t(ax, mx + 62, my + mh - 118, "!", 16, "white", "bold", "center")
        _t(ax, mx + 90, my + mh - 118, textwrap.shorten(spec["callout"], 70, placeholder="…"), 19, "#5F6368")
    if spec.get("button"):
        _box(ax, mx + mw - 170, my + mh - 66, 130, 46, "#1A73E8", r=8, z=5)
        _t(ax, mx + mw - 105, my + mh - 43, spec["button"], 22, "white", "bold", "center")
    return fig, plt


def _cards(spec):
    cards = spec["cards"]
    cols = min(len(cards), 3)
    h = 150 + 190 * -(-len(cards) // cols)
    plt, fig, ax = _canvas(h)
    ax.add_patch(plt.Rectangle((0, 0), W, h, fc="#1F1F1F", ec="none", zorder=0))
    _t(ax, 70, 70, spec["title"], 34, "white", "bold")
    cw = (W - 140 - (cols - 1) * 30) / cols
    for i, c in enumerate(cards):
        r, k = divmod(i, cols)
        x, y = 70 + k * (cw + 30), 120 + r * 190
        first = i == 0
        _box(ax, x, y, cw, 170, "#2B2B2B", "#F4511E" if first else "#3C4043", 14, 2.5 if first else 1.5, z=2)
        _icon(ax, c.get("icon", "plus"), x + 56, y + 62, 28, "#8AB4F8")
        _t(ax, x + 100, y + 62, c["title"], 26, "#8AB4F8" if first else "white", "bold")
        if c.get("subtitle"):
            _t(ax, x + 100, y + 104, c["subtitle"], 19, "#9AA0A6")
    return fig, plt


def render_scene_png(spec):
    import io
    fig, plt = {"banner": _banner, "ui_screen": _ui_screen, "cards": _cards}[spec["type"]](spec)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    return buf.getvalue()
