"""Visuals: parse `visual` fenced blocks in a draft, validate their specs and render them to PNG (matplotlib)."""
import io
import re

import yaml

import scenes

VISUAL_BLOCK = re.compile(r"^```visual[ \t]*\n(.*?)^```[ \t]*$", re.S | re.M)
TYPES = ("flow", "bar", "line") + scenes.SCENE_TYPES
MAX_NODES, MAX_POINTS, MAX_SERIES = 8, 12, 4


def parse_blocks(body):
    """Return [(spec_or_None, error_or_None)] for every `visual` block in `body`, in document order."""
    out = []
    for m in VISUAL_BLOCK.finditer(body):
        try:
            spec = yaml.safe_load(m.group(1))
        except yaml.YAMLError as e:
            out.append((None, f"invalid YAML: {str(e).splitlines()[0]}"))
            continue
        err = spec_error(spec)
        out.append((None, err) if err else (spec, None))
    return out


def _strings(v, lo, hi):
    return isinstance(v, list) and lo <= len(v) <= hi and all(isinstance(x, (str, int, float)) and str(x).strip() for x in v)


def spec_error(spec):
    """Return a message if `spec` is not a valid visual spec, else None."""
    if not isinstance(spec, dict):
        return "spec must be a mapping"
    if spec.get("type") not in TYPES:
        return f"type must be one of {', '.join(TYPES)}"
    if not isinstance(spec.get("title"), str) or not spec["title"].strip():
        return "title is required"
    if spec["type"] in scenes.SCENE_TYPES:
        return scenes.scene_error(spec)
    if spec["type"] == "flow":
        nodes = spec.get("nodes")
        if not _strings(nodes, 2, MAX_NODES):
            return f"nodes must be a list of 2-{MAX_NODES} labels"
        nodes = [str(n) for n in nodes]
        if len(set(nodes)) != len(nodes):
            return "node labels must be unique"
        edges = spec.get("edges")
        if not isinstance(edges, list) or not edges:
            return "edges must be a non-empty list of [from, to] pairs"
        for e in edges:
            if not (isinstance(e, list) and len(e) == 2 and all(str(x) in nodes for x in e)):
                return f"edge {e!r} must be a [from, to] pair of node labels"
        return None
    labels, series = spec.get("labels"), spec.get("series")
    if not _strings(labels, 2, MAX_POINTS):
        return f"labels must be a list of 2-{MAX_POINTS} items"
    if not isinstance(series, list) or not 1 <= len(series) <= MAX_SERIES:
        return f"series must be a list of 1-{MAX_SERIES} items"
    for s in series:
        vals = s.get("values") if isinstance(s, dict) else None
        if not (isinstance(s.get("name"), str) and isinstance(vals, list) and len(vals) == len(labels)
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals)):
            return "each series needs a name and one numeric value per label"
    return None


def count_scenes(body):
    """Number of valid topic illustrations (banner / ui_screen / cards) in `body`."""
    return sum(1 for s, e in parse_blocks(body) if s and s["type"] in scenes.SCENE_TYPES)


def count_valid(body):
    blocks = parse_blocks(body)
    return sum(1 for s, e in blocks if not e), [e for s, e in blocks if e]


def _layers(nodes, edges):
    """Column index per node: longest path from the sources, ignoring edges that would close a cycle."""
    col = {n: 0 for n in nodes}
    for _ in nodes:
        for a, b in edges:
            if col[b] < col[a] + 1 and col[a] + 1 < len(nodes):
                col[b] = col[a] + 1
    return col


def render_png(spec):
    """Render a valid spec to PNG bytes."""
    if spec["type"] in scenes.SCENE_TYPES:
        return scenes.render_scene_png(spec)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    buf = io.BytesIO()
    if spec["type"] == "flow":
        nodes = [str(n) for n in spec["nodes"]]
        edges = [(str(a), str(b)) for a, b in spec["edges"]]
        col = _layers(nodes, edges)
        by_col = {}
        for n in nodes:
            by_col.setdefault(col[n], []).append(n)
        ncols, nrows = max(by_col) + 1, max(len(v) for v in by_col.values())
        fig, ax = plt.subplots(figsize=(max(6, 2.2 * ncols), max(2.6, 1.3 * nrows + 0.8)))
        pos = {n: (c, (len(v) - 1) / 2 - i) for c, v in by_col.items() for i, n in enumerate(v)}
        w, h = 0.78, 0.5
        for n, (x, y) in pos.items():
            ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                        fc="#e8f0fe", ec="#1a73e8", lw=1.5))
            ax.text(x, y, n, ha="center", va="center", fontsize=9, wrap=True)
        for a, b in edges:
            (x1, y1), (x2, y2) = pos[a], pos[b]
            ax.annotate("", xy=(x2 - w / 2 if x2 > x1 else x2, y2 if x2 > x1 else y2 + (h / 2 if y2 < y1 else -h / 2)),
                        xytext=(x1 + w / 2 if x2 > x1 else x1, y1 if x2 > x1 else y1 + (-h / 2 if y2 < y1 else h / 2)),
                        arrowprops=dict(arrowstyle="->", color="#5f6368", lw=1.5, shrinkA=0, shrinkB=0))
        ax.set_xlim(-0.6, ncols - 0.4)
        ax.set_ylim(min(y for _, y in pos.values()) - 0.6, max(y for _, y in pos.values()) + 0.6)
        ax.axis("off")
    else:
        fig, ax = plt.subplots(figsize=(7, 3.6))
        labels = [str(x) for x in spec["labels"]]
        series = spec["series"]
        if spec["type"] == "bar":
            width = 0.8 / len(series)
            for i, s in enumerate(series):
                ax.bar([j + i * width for j in range(len(labels))], s["values"], width, label=s["name"])
            ax.set_xticks([j + 0.4 - width / 2 for j in range(len(labels))])
            ax.set_xticklabels(labels)
        else:
            for s in series:
                ax.plot(labels, s["values"], marker="o", label=s["name"])
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        if len(series) > 1:
            ax.legend(frameon=False)
        if spec.get("y_label"):
            ax.set_ylabel(str(spec["y_label"]))
        plt.setp(ax.get_xticklabels(), fontsize=8)
    fig.suptitle(spec["title"], fontsize=11, fontweight="bold")
    fig.tight_layout()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    return buf.getvalue()
