"""Charts: a thin wrapper over the existing matplotlib renderer in scripts/visuals.py."""
import visuals

from . import RenderError, image_result


def render(visual, out_dir):
    spec = {**visual["source"], "title": visual["title"]}
    if spec.get("type") not in ("bar", "line"):
        raise RenderError("chart: type must be bar or line")
    if err := visuals.spec_error(spec):
        raise RenderError(f"chart: {err}")
    (out_dir / f"{visual['id']}.png").write_bytes(visuals.render_png(spec))
    return image_result(out_dir, f"{visual['id']}.png")
