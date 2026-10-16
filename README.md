# AI Blog Automation

Turn a short brief into a reviewed blog draft, a Google Doc and a Slack notification. A human always publishes.

A Python state machine (`scripts/blog.py`) makes every gate decision. Claude only orchestrates, writes and reviews.

## How it works

```
brief -> writer -> deterministic checks -> reviewer -> gate -> Google Doc -> Slack
              ^______________ revise (up to 3 iterations) ______|
```

1. **Write:** the `blog-writer` subagent drafts the post from the brief and `config/guidelines.md`.
2. **Check:** mechanical rules run on the draft (title and meta length, headings, forbidden terms, placeholders, secret/PII patterns).
3. **Review:** the `blog-reviewer` subagent critiques the draft in isolation and returns structured issues.
4. **Gate:** `blog.py` passes the draft only if there are no critical or high issues. It loops back to the writer, stops on stagnation or after the iteration limit, or passes.
5. **Visuals:** once the text has passed review, the `visual-planner` subagent decides what visual, if any, best explains each section. Code then renders it with the right tool (see below).
6. **Deliver:** the draft is created as a Google Doc in a `Blogs` folder, verified, and announced in Slack.

Limits live in [config/thresholds.json](config/thresholds.json) and checks in [config/rules.json](config/rules.json).

## Visuals

The planner decides WHAT each section needs; deterministic renderers decide HOW. Policy (which intent may use which renderer, budgets, limits) lives in [config/visuals.json](config/visuals.json), and the plan format in [config/schemas/visual_plan.json](config/schemas/visual_plan.json). Turn the stage off with `"enabled": false`.

| Need | Renderer |
|---|---|
| Real product screen | `screenshot` via Chrome DevTools MCP, with a human signing in and approving it |
| Flow, architecture, sequence, relationships | `mermaid`, rendered locally (no API key) |
| Comparison, timeline, layers | `svg` Python templates to PNG |
| Data you can source | `chart` (matplotlib bar or line) |
| Official logos | `logo` from the vendored simple-icons subset in `assets/logos/` |
| Hero or conceptual art, diagrams | `ai_image`: after planning, Claude calls `create_asset` of the vendored [claude-image-gen](https://github.com/guinacio/claude-image-gen) MCP (`mcp_servers/`), `blog.py submit-image` validates and shrinks the file, and it is embedded in the Doc. Needs `GEMINI_API_KEY` in your dotenv file and Node 20+. A dry run, or `"image_backend": "placeholder"` in `config/visuals.json`, gives the old **IMAGE TO ADD** boxes instead. |
| Code | the draft's own fenced code blocks (`code` only for code the text lacks) |
| Anything where prose or a table is clearer | no visual |

A section with no visual is a valid plan. A visual that fails to render gets one planner retry, then its illustration fallback or is dropped (a `required` one waits for you). A screenshot always needs your confirmation that the screen is right and shows no sensitive data. Claude only navigates and captures, and never types credentials. Dry runs skip screenshots.

The Mermaid renderer needs Node.js (`npx`) and Chrome (set `BLOG_CHROME` to use another binary). The SVG and logo renderers need Cairo (`brew install cairo` on macOS). Run `evals/run_visual_eval.py` to check the planner against the golden blogs in `evals/golden_visuals/`.

## Setup

Requires Python 3.10+ and [Claude Code](https://claude.com/claude-code).

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

**Slack:** create a Slack app with the `chat:post` scope, install it, invite the bot to your channel, and set `SLACK_BOT_TOKEN` in `.env`. Put the channel ID in [config/delivery.json](config/delivery.json).

**Google Drive:**
1. In Google Cloud, enable the Drive API and create an OAuth client of type **Desktop app**.
2. Save the downloaded JSON as `secrets/google-oauth-client.json`.
3. Run `./.venv/bin/python mcp_servers/drive_auth.py` once and sign in. It saves a token to `secrets/google-token.json`.

The `blog-drive` and `blog-slack` MCP servers are registered in [.mcp.json](.mcp.json) and start automatically with Claude Code.

## Usage

Inside Claude Code:

```
/blog how to integrate Firebase with Flutter     # interview -> proposed brief -> you confirm -> run
/blog briefs/firebase-flutter.md --dry-run       # existing brief, full loop, no Drive or Slack calls
/blog briefs/firebase-flutter.md                 # real run
/blog --resume <run-id>                          # continue an interrupted run
```

With a topic instead of a file, the skill asks at most four questions at a time, proposes inferred defaults (keywords, depth, references, 1000-1500 words), shows the full brief for you to edit, and only then writes `briefs/<slug>.md` and starts the run. The interview never creates a run.

A brief is YAML front matter plus optional free-form notes. See [briefs/sample.md](briefs/sample.md) and [briefs/firebase-flutter.md](briefs/firebase-flutter.md). Required: `topic`, `audience`, `primary_keyword`, `tone`, `target_words`. Optional: `content_type`, `purpose`, `reader_takeaway`, `technical_depth`, `examples`, `original_angle` (null if none), `references`, `must_include`, `must_avoid`.

Run state, drafts and reviews are stored under `runs/<run-id>/` (gitignored). `blog.py status <run-id>` shows where a run stands.

## Improve an existing draft

`/blog` also starts from something that already exists. Three ways to begin:

```
/blog drafts/post.md                                # a local .md, .mdx, .txt or .docx draft
/blog https://docs.google.com/document/d/<id>/edit  # a Google Doc you can open
/blog                                               # asks whether to create or improve
```

The skill asks for your goal (clarity, tighten, SEO, accuracy, tone, restructure), the audience and any text that must stay, then writes an improve brief for you to approve. The reviewer first assesses the original and shows you what it found. The writer then edits a copy in place, the usual checks and review gate decide, and the result is a new Doc plus a change log (`runs/<run-id>/delivery/changes.md`). Your original is never modified. A draft that already passes every check ends with no Doc.

If a revised draft fails the reviewer gate, the run stops as usual. In improve mode only, you can choose to deliver it anyway for human review: `blog.py approve-failing <run-id> --approved-by-human --note "<your reason>"`. The Doc and Slack message are labelled as failing. Mechanical hard-check failures (dead links, secrets, injection phrases, flagged words) can never be overridden.

## Review scoring

The reviewer scores ten rubric dimensions (weights in [config/rules.json](config/rules.json)) and `blog.py` computes the result. A draft passes only if all of these hold: no CRITICAL/HIGH issues, the weighted total is at least `min_total_score` (75), `technical_accuracy` and `originality` are each at least `min_dimension_percentage` (60), `factual_correctness.passed` is true, and no claim check is UNSUPPORTED or CONTRADICTED. Thresholds live in [config/thresholds.json](config/thresholds.json). `hard_gates.factual_correctness: true` enables that gate; it is not the expected review value.

## Project layout

| Path | Purpose |
|------|---------|
| `scripts/` | State machine (`blog.py`), checks, validation, message rendering |
| `mcp_servers/` | Local Drive and Slack MCP servers and the OAuth helper |
| `.claude/skills/blog/` | The `/blog` orchestration skill |
| `.claude/agents/` | Writer and reviewer subagents |
| `.claude/hooks/` | Secret protection hook |
| `config/` | Thresholds, rules, guidelines, delivery target, JSON schemas |
| `briefs/` | Input briefs |
| `evals/` | Offline reviewer eval with a golden set |
| `tests/` | Pytest suite |

## Testing

```bash
./.venv/bin/python -m pytest tests
./.venv/bin/python evals/run_eval.py     # reviewer recall and false-positive rate; uses `claude -p`
```

Re-run the eval whenever models, prompts, guidelines or rules change.

## Safety

- Delivery tools run through an `allow-delivery` hook, so only a run that passed review can create a Doc or post to Slack.
- Subagents can write only to `runs/<id>/incoming/`.
- `.env` and `secrets/` are gitignored and blocked from Claude by a hook and deny rules. Never commit them.
- The cloud claude.ai Drive and Slack connectors are denied. Only the local servers are used.
