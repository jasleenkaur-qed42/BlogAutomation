---
title: "AI Pull Request Review with GitHub Actions: A Practical Setup"
slug: ai-pull-request-review-github-actions
description: "Learn how an AI pull request review step fits your existing process, what to automate, what humans keep, and how to wire a basic GitHub Actions workflow."
keywords:
  - AI pull request review
  - code review automation
  - GitHub Actions
  - pull request workflow
claims:
  - claim: "The permissions key lets you limit the GITHUB_TOKEN to the access a workflow or job needs."
    source: https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/controlling-permissions-for-github_token
  - claim: "pull_request_target has security risks and needs careful use because it runs with elevated context."
    source: https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target
---

# AI Pull Request Review with GitHub Actions: A Practical Setup

```visual
type: banner
title: AI pull request review
subtitle: A review step that supports your human reviewers
tiles: [{label: GitHub Actions, icon: gear}, {label: Pull request, icon: code}, {label: Reviewer, icon: user}]
```
*Figure 1: Illustration of the topic.*

Small teams often have one or two people who review every pull request. Reviews pile up, and reviewers spend their attention on typos, missing null checks and style nits instead of design. An AI pull request review step can take some of that first-pass work. It does not replace the people who decide whether a change should ship.

This article treats code review automation as a first-pass helper. It shows where an AI review step sits in a pull request pipeline, what to automate and what to leave to humans, and a basic GitHub Actions workflow you can adapt.

## How the AI step fits into the pipeline

An AI review step is one more automated check, like a linter or test run. It reads the diff, asks a large language model (LLM) for feedback, and posts the result as a comment. The LLM generates plausible text from the diff you give it. It does not run your code and it can be wrong, so treat its output as suggestions.

```visual
type: flow
title: How a pull request moves through the AI review step
nodes: [Open PR, Tests and lint, AI review job, PR comment, Human review, Merge]
edges: [[Open PR, Tests and lint], [Tests and lint, AI review job], [AI review job, PR comment], [PR comment, Human review], [Human review, Merge]]
```
*Figure 2: The AI step runs after deterministic checks and before a human reads the change.*

Figure 2 shows the order. Deterministic checks run first because they are cheap and reliable. The AI job runs next and leaves a comment. The human reviewer then reads the change with that comment as extra context. Merging stays a human decision.

## What to automate and what humans keep

A useful rule is to automate feedback that is checkable from the diff alone, and keep judgment calls with people.

| Good for the AI step | Keep with humans |
| --- | --- |
| Summarizing what the change does | Whether the change solves the right problem |
| Spotting missing error handling or edge cases | Architecture and long-term design fit |
| Flagging unclear names and missing tests | Security-sensitive logic and access decisions |
| Pointing out inconsistencies with the diff description | Approving and merging |

The reason for the split is context. The model sees only what you send it, usually the diff and perhaps a few files. It does not know your roadmap, your incident history or why a past decision was made. It can also state wrong things confidently, so a human must verify anything it raises before acting on it.

## Wiring a basic workflow

The example below runs on pull requests, collects the diff, calls a script that you write, and posts the output as a comment. The versions (`actions/checkout@v4`, `actions/github-script@v7`) are examples; check each action's releases for the current major version.

```yaml
name: ai-review
on:
  pull_request:
    types: [opened, synchronize]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Build diff
        run: git diff origin/${{ github.base_ref }}...HEAD > pr.diff
      - name: Ask the model
        env:
          LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
        run: python scripts/ai_review.py pr.diff > review.md
      - name: Post comment
        uses: actions/github-script@v7
        with:
          script: |
            const body = require('fs').readFileSync('review.md', 'utf8');
            await github.rest.issues.createComment({
              ...context.repo,
              issue_number: context.issue.number,
              body: `AI review (suggestions only):\n\n${body}`,
            });
```

`scripts/ai_review.py` is yours to write: it should send the diff and a short review prompt to whichever model API you use, and print markdown. The key decisions are in the workflow itself:

- **Least privilege.** The `permissions` block limits the token to reading code and writing pull request comments ([GitHub docs](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/controlling-permissions-for-github_token)).
- **Comment, do not block.** The job posts a comment and does not set a required status check, so a bad suggestion never stops a merge.
- **Label the output.** The prefix tells reviewers this is machine-generated.

## Limits and security trade-offs

Fork pull requests are the main trap. Switching the trigger to `pull_request_target` is tempting because it runs with a more privileged context, but GitHub documents real risks if it runs untrusted code ([GitHub docs](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)). For a small team that merges branches from the same repository, the simple `pull_request` setup is the safer choice.

Also consider:

- **Data sharing.** The diff is sent to a third-party API. Check that your policy allows this for the repository, and keep secrets out of diffs.
- **Prompt injection.** A diff or code comment can contain text that tries to steer the model. Never give the AI job write access beyond comments, and never let it merge.
- **Cost and noise.** Large diffs cost more and produce vaguer feedback. Skip generated files and cap diff size.
- **Reliability.** Output varies between runs. Do not build gates on it.

## Conclusion

An AI pull request review step works best as a fast first pass between your automated checks and your human reviewers. Automate what can be judged from the diff, keep design, security and approval with people, and give the job the narrowest permissions it needs. Start with the workflow above, watch whether reviewers find the comments useful, and tune the prompt before expanding what the step does.

## References

- [Controlling permissions for GITHUB_TOKEN, GitHub Docs](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/controlling-permissions-for-github_token)
- [Securely using pull_request_target, GitHub Docs](https://docs.github.com/en/actions/reference/security/securely-using-pull_request_target)
