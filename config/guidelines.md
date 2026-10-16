# Blog guidelines

Structure is guidance, not a checklist for prose generation. Use sections when they improve comprehension. Do not create artificial sections merely to satisfy the recommended outline. A short conceptual article does not need ten sections.

## Brand and tone
- Clear, practical, confident but not hype. Plain language, active voice.
- Educational, not promotional. No superlatives without evidence, no competitor bashing, no buzzwords without an explanation.

## Brief fields
- `purpose` is what the article is trying to accomplish. `reader_takeaway` is what the reader should know or be able to do afterward. Treat them as different things and make sure the article delivers every takeaway.
- `examples.preferred` lists technologies, implementation scenarios or examples to prefer when illustrating the concept. It does not mean the author personally built them. Never claim personal experience.
- If `original_angle` is null, develop an original explanatory perspective where appropriate (your own explanation, synthesis, trade-off reasoning). Do not fabricate personal experience, project history, metrics or lessons learned.

## Recommended outline
Use what fits the topic. Order moves from problem to concept to implementation to conclusion.

```
# Title                      clear, specific, practical value, no clickbait
Introduction                 the problem, why it matters, the intended reader, what they will learn
## Background / Context      only the concepts and terms the reader needs first
## Core Concept              how and why, simple first then deeper
## Practical Implementation  prerequisites, assumptions, code or configuration, key decisions
## Real-World Use Cases      realistic scenarios and when the approach fits
## Advantages, Limitations & Trade-offs   what it solves, where it falls short, cost, complexity, security, when not to use it
## Best Practices            patterns, security, performance, maintainability, common mistakes
## Alternatives              conditional: only when a comparison helps the reader
## Conclusion                the takeaways; no new concepts
## References                official docs, specifications, repositories that support the claims
```

Mechanically required (checked by code): an introduction, at least three substantive topic sections (Conclusion and References do not count), a conclusion, and a References section when the brief requires references. Everything else is judged by the reviewer.

## Quality bar
- Technically accurate claims, terminology and code. No invented APIs, benchmarks, statistics, quotes or references.
- Original value beyond reproducing official documentation: the author's own explanation, example, analysis or perspective.
- At least one practical example, implementation, diagram, comparison or real-world scenario, with limitations and trade-offs discussed.
- Topic images (only when the prompt requires `visual` blocks; otherwise write none, because figures are planned after review): open with a `banner`, and use `ui_screen` or `cards` illustrations for setup steps and dashboards, captioned as illustrations (never presented as real screenshots). Code goes in fenced blocks with a language tag.
- Visuals for clarity (same condition): at least the brief's `visuals.min` (default 2) diagrams or charts, each written as a `visual` block (see the writer instructions) with an italic caption, and each referenced or explained in the surrounding text. Charts must not present invented data as fact.
- Important claims are supported by reliable sources. Every statistic or externally verifiable claim needs a source in the `claims` front matter and a link in the text.
- Version-dependent behavior states the version or range. Versions come from the brief or verified documentation, or are labeled as an example. Do not present a toy example as production-ready without saying so.
- Security, privacy and performance implications are addressed when relevant.
- Understandable without already knowing the whole subject. Short paragraphs, useful headings, lists, tables and examples.
- Natural SEO: the title, headings and terms reflect what readers search for.

## AI-related topics (apply only when the article is about AI)
- Distinguish AI, ML, LLM, generative AI, RAG, agents and MCP. Explain the actual mechanism instead of repeating "AI-powered".
- Distinguish LLM capability from deterministic application logic. State limitations (hallucination, context, latency, cost, reliability).
- For agents, explain tools, orchestration, state, permissions and failure handling. For RAG, explain retrieval, chunking, embeddings and generation. For evaluation, explain how quality is measured.
- Name the model, provider and version when behavior depends on it. Do not present experimental behavior as deterministic. No claims like "AI will replace developers" or "this model is the best".

## Must not
- Be primarily a rewritten version of another article, a collection of generic AI statements, or promotional.
- Make unsupported performance, cost or security claims.
- Use outdated APIs or libraries without stating the version.

## Links
- Only link to sources you have verified exist.
