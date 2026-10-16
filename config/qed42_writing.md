# QED42 writing standards

The reviewer runs the QED42 blog review system (`.claude/skills/review/SKILL.md`) on every draft. Write so the draft passes it the first time. The flagged-words list, the em dash ban and the FAQ structure are also enforced by code.

## Before you write
Answer these in your head; never put the answers in the post.
1. If no one reads this, why write it? If the answer is empty, the angle is wrong.
2. How does it earn the read? Decide the one idea a reader would repeat to a colleague.
3. Who is the one reader? Use the brief's `audience_type` (community, cto or business). If it is missing, infer it from `audience` and stay with it all the way through.
   - community: peer engineers and designers. Peer level, real tradeoffs and dead ends, no explaining basics, no pitch.
   - cto: decision-makers at US enterprises. Judgment, scale, cost, risk and team impact. Some altitude, not a code walkthrough.
   - business: non-technical leaders. Lead with the outcome, plain language, a light mechanism, no code.
4. Which official page would this reader read instead (docs, README, vendor page)? Add what it leaves out: the context, the judgment, the failure mode, the tradeoff.

## Shape of the post
- Title: descriptive and honest to the introduction. No clickbait, no promise the post does not keep. Sentence case.
- Introduction: open with a concrete scene or question the reader recognises (second person works well), then say what the post covers. Never invent a personal anecdote, project or number. Use only experience that is in the brief or its notes. Title, introduction and conclusion must read as one story when skimmed alone.
- No subheading directly under the title; the introduction goes first.
- Headings: descriptive (say what the section says, never "Introduction" or "Part two"), sentence case, capital letters only on the first word and proper nouns.
- TLDR: when the post is longer than about 900 words, add a 3 to 4 line TLDR right after the introduction that a machine could lift as a summary.
- One clear claim near the top. Short paragraphs, one idea each.
- Body: at least one original insight a reader could only get from someone who did the work: a named tradeoff, a failure mode, a real number with a source, a call you only learn by shipping. If the brief gives none, build it from reasoning and verified sources and never fabricate experience.
- Code: complete enough to copy, idiomatic for the stack, and consistent with the prose around it. Say what is omitted.
- Conclusion: one thought the reader did not have at the start. Call back to the exact scene, question or claim the introduction opened with and end on one line to carry. No recap of the body, no new idea, no product endorsement, no generic sign-off.
- FAQ: an H2 titled "Frequently asked questions" with 5 to 7 questions as H3 headings that end in `?`, each followed by a tight direct answer. Ask what a reader would genuinely ask after reading, phrased the way they would type it into a search box. Never restate the body.
- Payoff: the reader should walk away knowing, able to do or ready to reconsider something specific. Deliver every `reader_takeaway`.

## Voice rules (always on)
- Capital letters only on the first word of a sentence, title or heading, and on proper nouns.
- No em dashes. Use commas, periods, semicolons or a new sentence.
- Lead positive and forward: what something does, not what it avoids. Write "every step shown clearly", not "no confusing steps". No "not just X but Y", no "rather than", no "X, not Y", and no opening on a fear or worst case.
- Active voice with a named actor ("we migrated the site", "the platform enforces the rule"). Keep passive only when the actor is unknown or the object is the story.
- Simple tenses ("we built", not "we have been building"). Contractions (you're, it's). Speak to the reader as "you".
- Short sentences, one thought each. No run-ons, comma splices or trailing restarts.
- Name real things: real tools, real numbers, real projects. QED42 is a company, never an agency.
- Avoid AI rhythm: padded three-part lists, "not only X but also Y", openers like "in the world of".
