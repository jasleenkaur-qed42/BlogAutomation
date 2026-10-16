"""AI images are not generated here. The Doc gets a visible placeholder carrying the prompt, and a human
generates the image and inserts it after upload. No network call, no key."""
from . import RenderError

LABELS = {"hero": "Hero", "concept": "Concept"}


def render(visual, out_dir):
    src = visual["source"]
    if visual["intent"] not in LABELS:
        raise RenderError("ai_image: only hero and concept intents may use an image prompt")
    prompt = " ".join(src["prompt"].split())
    if src.get("negative"):
        prompt += f" Avoid: {' '.join(src['negative'].split())}"
    return {"kind": "placeholder", "label": LABELS[visual["intent"]], "aspect": src["aspect"], "prompt": prompt,
            "alt": visual["alt"], "caption": visual["caption"]}
