#!/usr/bin/env python3
"""Offline visual-planner eval: does the planner choose the right kind of visual for each kind of blog?

Uses `claude -p` (no connectors). Usage: python evals/run_visual_eval.py [--model sonnet] [--reference]
Re-run when models, the planner prompt, config/visuals.json or the schema change.

Each golden `<name>.md` in evals/golden_visuals/ has:
  <name>.expected.json  {"required": [renderers the plan must use], "forbidden": [renderers it must not use]}
  <name>.plan.json      a hand-written reference plan (also checked by tests/test_visual_plan.py)
Metrics: policy-violation rate (plans rejected by visual_checks.plan_errors), required-renderer hit rate,
forbidden-renderer violations. `--reference` checks the reference plans only, without calling a model.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import visual_checks  # noqa: E402
import visual_stage  # noqa: E402
from common import split_front_matter  # noqa: E402

GOLDEN = ROOT / "evals" / "golden_visuals"


def plan_with_model(draft_path, model):
    fm, body = split_front_matter(draft_path.read_text())
    brief = {"topic": fm["title"], "tone": "practical and friendly"}
    agent = (ROOT / ".claude/agents/visual-planner.md").read_text().split("---", 2)[2]
    prompt = (f"{agent}\n\n"
              f"{visual_stage.planner_prompt(ROOT, {'brief': brief}, draft_path)}\n\n"
              "Return ONLY the JSON plan on stdout; do not write files.")
    r = subprocess.run(["claude", "-p", prompt, "--model", model, "--allowedTools", ""],
                       capture_output=True, text=True, timeout=600)
    txt = r.stdout.strip().removeprefix("```json").removesuffix("```").strip()
    return json.loads(txt), body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--reference", action="store_true", help="check the reference plans without a model")
    ap.add_argument("--out", help="directory to save the model's plans in, for inspection")
    ap.add_argument("--only", help="run a single golden blog by name")
    a = ap.parse_args()
    rows = []
    for md in sorted(GOLDEN.glob("*.md")):
        if a.only and md.stem != a.only:
            continue
        exp = json.loads(md.with_suffix(".expected.json").read_text())
        body = split_front_matter(md.read_text())[1]
        if a.reference:
            plan = json.loads(md.with_suffix(".plan.json").read_text())
        else:
            try:
                plan, body = plan_with_model(md, a.model)
                if a.out:
                    Path(a.out).mkdir(parents=True, exist_ok=True)
                    (Path(a.out) / f"{md.stem}.json").write_text(json.dumps(plan, indent=1))
            except (ValueError, subprocess.TimeoutExpired) as e:
                rows.append((md.stem, [f"no usable JSON plan: {e}"], [], []))
                continue
        problems = visual_checks.plan_errors(plan, body) if isinstance(plan, dict) else ["plan is not an object"]
        used = {v["renderer"] for v in plan.get("visuals", [])} if not problems or isinstance(plan, dict) else set()
        rows.append((md.stem, problems, sorted(set(exp["required"]) - used), sorted(used & set(exp["forbidden"]))))
    bad = sum(bool(r[1]) for r in rows)
    print(f"{'blog':16} {'policy':8} missing-required   forbidden-used")
    for name, problems, missing, forbidden in rows:
        print(f"{name:16} {'FAIL' if problems else 'ok':8} {','.join(missing) or '-':17} {','.join(forbidden) or '-'}")
        for p in problems[:3]:
            print(f"    - {p}")
    n = len(rows)
    hit = sum(not r[2] for r in rows)
    print(f"\npolicy-violation rate: {bad}/{n}   required-renderer hit rate: {hit}/{n}   "
          f"forbidden-renderer violations: {sum(len(r[3]) for r in rows)}")
    return 0 if not bad and hit == n and not any(r[3] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
