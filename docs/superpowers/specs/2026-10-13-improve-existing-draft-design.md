# Improve an existing draft or Google Doc: design

Date: 2026-10-13. Status: awaiting user review.

## Goal
`/blog` can start three ways: **create** a new blog from a brief or topic (today), **improve a local draft** (`.md`, `.mdx`, `.txt`, `.docx`), or **improve a Google Doc** (URL). Improve modes read the content, ask what the user wants to achieve, review it with the QED42 review system, and return a revised draft plus a change log for human review.

## Agreed constraints
- Output is a revised draft plus a change log (user choice). Not suggestions-only, not per-suggestion approval.
- The original is never modified or overwritten (local file or Google Doc). The revised text always goes to a new Doc.
- Gates are never bypassed silently. In improve mode only, a human may approve delivering a draft that failed the gate (section 4a); the result is labelled as failing everywhere.
- Nothing is published automatically. Existing delivery gates (`allow-delivery` hook, `verify-doc`, Slack step) are unchanged.
- Google access only through the local `blog-drive` MCP with the user's OAuth. The cloud connectors stay denied.
- Source content is untrusted data under `config/untrusted_content.md`.
- Gate decisions stay in `blog.py`, `validate.py` and `config/`, never in prompts.
- Existing states, schemas and the 276 passing tests keep working unchanged for create mode.

## Approach
Normalize every input to markdown (`runs/<id>/source.md`), add one `ASSESS` phase before WRITE, and reuse the existing write/check/review/gate/delivery loop. The writer edits a prefilled copy of the source in place, the mechanism revisions already use.

## 1. Entry and intake (`.claude/skills/blog/SKILL.md`)
Argument classification:
- `docs.google.com/document/d/<id>` URL: improve Google Doc.
- Existing path ending `.md`, `.mdx`, `.txt`, `.docx` whose front matter is not a brief (no `topic` and `audience`): improve local draft. A `.md` that is a valid brief stays create mode.
- Other existing brief file, or a plain topic: create (unchanged intake).
- No argument: ask which of the three modes.

Improve intake (never creates a run before approval):
1. Ask the goal, multi-select: clarity, tighten, SEO, technical accuracy, tone or voice, restructure, other.
2. Ask audience type (community, cto, business), the primary keyword, and sections or facts that must be kept.
3. Defaults, shown not asked: tone preserved from the source; length range is the source's word count ±15%.
4. Write `briefs/<slug>.md` with `mode: improve`, `source: {kind: local|gdoc, ref: <path or URL>}`, `goal`, plus the usual brief fields. Show the path, then ask Approve or Request changes, as in create intake.

## 2. Brief schema (`config/schemas/brief.json`)
- Add optional `mode` (`create` default, `improve`), `source` (`kind`, `ref`), `goal` (string or list, required when `mode: improve`), `keep` (list).
- `topic` stays required (the skill derives it from the source title). `target_words` stays required (derived).
- Existing briefs validate unchanged.

## 3. Source import (`scripts/source_import.py`, called from `cmd_init`)
- Output: `runs/<id>/source/original.<ext>` (byte copy plus sha256 in state) and `runs/<id>/source.md` (normalized markdown).
- `.md`, `.mdx`, `.txt`: UTF-8 read. MDX imports and JSX blocks are kept verbatim and listed as "preserve" so the writer must not rewrite them. Existing front matter is parsed and kept.
- `.docx`: `mammoth` (docx to HTML) then `markdownify` (HTML to markdown). New pinned dependencies in `requirements.txt`; neither is installed today and pandoc is absent. Dropped elements (images, comments, tracked changes, tables beyond simple) are recorded in `source/import_notes.json` and shown to the user.
- Google Doc: new `blog-drive` tool `read_doc_markdown(doc_id, save_to)` exports the Doc as HTML through Drive and converts it to markdown, saving under `runs/` like `read_doc_to_file` (text stays out of the conversation). URL parsing (`/document/d/<id>`) lives in `source_import.py`. The skill calls the tool when `blog.py init` returns `FETCH_GDOC`, then `blog.py submit-source <run> <file>` stores it. The scope is already `drive`; no re-auth.
- Limits: max size and type checks, UTF-8 errors and unreadable Docs fail `init` with a clear message and no run is left behind. No `.env` or `secrets/` reads.
- Imported text is checked: empty, under 100 words, or with no headings fails with a clear message.

## 4. State machine (`scripts/blog.py`)
- Improve runs start `state: IN_PROGRESS`, `phase: ASSESS`, `mode: improve`. Create runs are untouched.
- `next` in `ASSESS` returns `{"action": "REVIEW", "kind": "assess", prompt, output}`. The reviewer prompt includes the source path, the goal, and the standard reviewer sections.
- `submit-assessment <run> <file>`: validates against the existing review schema and `validate.review_problems`, saves `assessment.json`, moves `phase` to `WRITE`. It does not gate, does not count as an iteration, and has its own malformed-retry limit from `thresholds.json`. Out-of-order calls raise `BlogError`.
- WRITE (iteration 1) prefills the output from `source.md` and builds an improve prompt: goal, assessment issues (CRITICAL and HIGH must be fixed, others best effort), "minimal diff", "preserve the author's voice, facts and any marked preserve blocks", "never invent claims, sources, metrics or experience", and a required `changes: [{section, reason}]` front matter list (schema `writer_front_matter.json` gains optional `changes`, required in improve mode).
- From the first submit-draft onward the loop is identical: hard checks, review, gate, retries, stagnation, `AI_REVIEW_PASSED` or `AI_REVIEW_FAILED`.
- Visual stage: skipped in improve mode unless the brief's `visuals` asks for it, so the author's existing figures are not duplicated. Existing images and figure lines in the source are preserved as text.

## 4a. Hard-gate failures in improve mode
The gates are unchanged and apply to the revised draft: mechanical checks, `UNSUPPORTED`/`CONTRADICTED` claim verdicts, the factual-correctness gate, `technical_accuracy` and `originality` minimums, HIGH/CRITICAL counts. The reviewer's verdict is still ignored; `validate.py` decides.
- **Surface problems first.** After `submit-assessment`, the skill prints a short summary from `assessment.json`: unverified or contradicted claims, broken or unfetchable links, hard-check failures in the source. The user may add a public source to the brief's `keep` notes or accept the cuts. The skill does not decide anything.
- **Removal, not rewording.** The existing rule applies: unverified claims, their links, `claims` entries and References entries are removed, never reworded or re-sourced. Every removal is listed in `changes.md` as "removed: <claim> (reviewer could not verify)", with the original text, so nothing the author wrote disappears unseen.
- **No silent bypass.** There is no config flag, brief field or prompt that skips a gate.
- **If the gate still fails** (iteration cap or stagnation), the run ends `AI_REVIEW_FAILED` as today, with `best_draft`, `changes.md` and the open issues saved locally. The skill's STOP step prints them and then asks (AskUserQuestion): "Stop" or "Deliver the failing draft for human review".
- **Human-approved failing delivery (improve mode only).** New command `blog.py approve-failing <run> --approved-by-human --note "<why>"`:
  - allowed only when `mode: improve` and `state: AI_REVIEW_FAILED`; any other state or mode raises `BlogError` (create-mode failures stay terminal);
  - records `gate_override: {note, approved_at, open_issue_ids, gate_failures, best_draft_sha256}` in `state.json` and `result.json`, and moves the run to `AI_REVIEW_PASSED`, the state `allow-delivery` already accepts, with `gate_override` set;
  - `notify.render_doc` and `render_slack` read `gate_override` and add a deterministic banner ("Did not pass the automated review gate. Open issues:" plus the HIGH/CRITICAL list and unverified claims) at the top of the Doc and in the Slack text. The banner is part of `doc.md`, so `verify-doc` still compares like with like;
  - the Doc title gets a `[FAILED GATE]` prefix before `[run:...]`, so the dedupe search keeps working;
  - delivery otherwise runs through the same `allow-delivery` hook, `verify-doc` and Slack steps. Nothing is ever published automatically, and the visual stage is skipped for overridden runs.
- The approval needs a human: the skill must ask the user with AskUserQuestion and pass the user's own words as `--note`. A subagent cannot call it, and the skill never decides.

## 5. Change log (`scripts/diff_report.py`)
- Deterministic: section-level diff of `source.md` against the final draft (per heading: added, removed, changed words), plus the unified diff, plus the writer's `changes` reasons. Written to `runs/<id>/delivery/changes.md`.
- `render-slack` appends a short change summary (counts and top sections changed) and the local path of `changes.md`. The Doc body stays the verbatim revised draft, so `verify-doc` is unchanged.
- The Doc title keeps the `[run:...]` form, so `search_title_first` and the existing dedupe logic apply unchanged.

## 6. Agents and prompts
- `blog-writer.md`: add an "improve mode" section (edit in place, minimal diff, voice preservation, `changes` front matter, no invented facts).
- `blog-reviewer.md`: add an assess mode (review the original against the goal; the output schema is unchanged).
- `config/qed42_review_adapter.md`: note that in assess mode severities drive the fix list, not a gate.
- The untrusted-content section is included in the assess and improve prompts. The source's embedded instructions are data; the reviewer reports injection attempts as HIGH.
- `guard_write.py` is unchanged: subagents still write only to `runs/<id>/incoming/`.

## 7. Errors and edge cases
- Any `blog.py` error is shown and the loop stops (existing rule); no workarounds.
- Google Doc not readable (permissions, wrong id): `init` fails, no Doc content is requested again.
- Source already passes review cleanly: the writer still runs once; the diff may be empty, and the change log says "no changes needed" instead of delivering a no-op Doc. In this case `blog.py` ends the run `DONE_NO_CHANGES` and does not create a Doc.
- Source over the word range: the range check uses the ±15% defaults, so a user-extended limit must be set in the brief.
- Lock behaviour: the lock is keyed on the source ref for improve runs.
- `--resume` and `--dry-run` work for improve runs the same way as create runs.

## 8. Testing (`tests/`)
- Mode detection (path, brief vs draft `.md`, URL, topic).
- Importers: md, mdx (preserve blocks), txt, docx fixtures built in-test, with dropped-element notes; a mocked Drive export for Google Docs; URL parsing and bad-URL errors.
- Brief schema: improve requires `goal`; create briefs unchanged.
- State: `ASSESS` to WRITE transition, out-of-order errors, malformed-assessment retries and stop, resume.
- Prompts: the improve writer prompt contains the goal, issues, preserve rules and the untrusted section; the assess prompt too.
- Change log: section diff, empty diff, `render-slack` append, `verify-doc` unchanged.
- Gate failures: removals are listed in `changes.md`; `approve-failing` is rejected in create mode, in any state other than `AI_REVIEW_FAILED`, and without `--approved-by-human`; an approved run carries `gate_override`, the banner and the title prefix in `doc.md`, `slack.txt` and the Doc title, and `verify-doc` still matches; the `allow-delivery` hook refuses a failed run that was not approved.
- Safety: source file hash unchanged after the run, no write access to existing Docs, `DONE_NO_CHANGES` does not call delivery.
- The full existing suite must still pass.

## Out of scope
- In-place edits of the original Doc or file, tracked-changes output, per-suggestion approval UI.
- Docs outside Google Docs (Notion, Confluence, Word online).
- Fixing `test_eval_reviewer.py` or the eval fixtures.
- Re-running the reviewer eval (do this separately if the reviewer prompt changes materially).
