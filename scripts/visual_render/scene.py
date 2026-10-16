"""Illustrations (banner, ui_screen, cards): a thin wrapper over scripts/scenes.py. These are drawings, never
screenshots, and the planner must caption them as illustrations."""
import scenes
import visuals

from . import RenderError, image_result


def render(visual, out_dir):
    spec = {**visual["source"], "title": visual["title"]}
    if spec.get("type") not in scenes.SCENE_TYPES:
        raise RenderError(f"scene: type must be one of {', '.join(scenes.SCENE_TYPES)}")
    if err := visuals.spec_error(spec):
        raise RenderError(f"scene: {err}")
    (out_dir / f"{visual['id']}.png").write_bytes(visuals.render_png(spec))
    return image_result(out_dir, f"{visual['id']}.png")
