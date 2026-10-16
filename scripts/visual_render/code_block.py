"""Code is not an image: it is emitted as a fenced code block, which the existing Markdown -> Docs conversion
already turns into a shaded, language-labelled block."""
from . import RenderError


def render(visual, out_dir):
    src = visual["source"]
    code = src["code"].rstrip("\n")
    if "```" in code:
        raise RenderError("code: must not contain a ``` fence")
    if len(code.split("\n")) > 60:
        raise RenderError("code: longer than 60 lines; show the relevant part")
    return {"kind": "code", "language": src["language"], "code": code}
