import io
import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import yaml
from conftest import LONG, SECTION, Driver, make_draft
import blog

# A realistic author draft: no FAQ, no conclusion, no references, 100+ words, no claim-trigger words.
SOURCE_MD = (f"# Design tokens for small teams\n\nSmall teams often ask whether tokens are worth the effort. {LONG}\n\n"
             f"## Why tokens help\n{SECTION}\n\n## When to adopt\n{SECTION}\n")


def make_docx(paras):
    """A minimal .docx from [(style_id_or_None, text)], built without python-docx."""
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    def p(style, text):
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        return f"<w:p>{ppr}<w:r><w:t>{escape(text)}</w:t></w:r></w:p>"
    parts = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>',
        "_rels/.rels": f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/_rels/document.xml.rels": f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="{rel}/styles" Target="styles.xml"/></Relationships>',
        "word/styles.xml": f'<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="{w}"><w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style><w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/></w:style></w:styles>',
        "word/document.xml": f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{w}"><w:body>{"".join(p(s, t) for s, t in paras)}</w:body></w:document>',
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return buf.getvalue()


def write_improve_brief(root, source, kind="local", **over):
    """Write briefs/improve.md for `source` (a path, or a Docs URL when kind is gdoc) and return its path."""
    fm = {"topic": "Design tokens for small teams", "audience": {"primary": "Front-end leads", "experience_level": "intermediate"},
          "primary_keyword": "design tokens", "secondary_keywords": ["design system", "css variables"],
          "tone": "practical and friendly", "mode": "improve", "goal": ["clarity", "tighten"],
          "source": {"kind": kind, "ref": str(source)}, "target_words": {"min": 700, "max": 1100}}
    fm.update(over)
    fm = {k: v for k, v in fm.items() if v is not None}
    path = Path(root) / "briefs" / "improve.md"
    path.write_text("---\n" + yaml.safe_dump(fm, sort_keys=False) + "---\nKeep the author's examples.\n")
    return path


class ImproveDriver(Driver):
    """A Driver whose run was started from a local draft instead of the sample brief."""

    def __init__(self, root, source_text=SOURCE_MD, dry_run=False, **brief_over):
        src = Path(root) / "drafts" / "post.md"
        src.parent.mkdir(exist_ok=True)
        src.write_text(source_text)
        self.root = root
        self.run = blog.cmd_init(root, write_improve_brief(root, src, **brief_over), dry_run)["run_id"]

    def assess(self, review):
        a = self.next()
        assert a["action"] == "REVIEW" and a["kind"] == "assess", a
        Path(a["output"]).write_text(json.dumps(review))
        return blog.cmd_submit_assessment(self.root, self.run, a["output"])


def revised(extra_changes="[{section: Frequently asked questions, reason: added the missing FAQ}]"):
    """A revised draft that passes every mechanical check for the sample-sized brief."""
    return make_draft(visuals=False, extra_fm=f"changes: {extra_changes}\n")
