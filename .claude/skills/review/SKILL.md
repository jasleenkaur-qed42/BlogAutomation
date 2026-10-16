---
name: qed42-blog-review-system
description: QED42 Blog Review System. Run a QED42 blog draft or published blog through the twelve review checks (audience, title, skim, conclusion, sentence boundaries, code, human words, fact-check, humans and machines, beats the docs, originality, so what) plus the always-on voice rules and the framing and active-voice passes. Use whenever someone asks to review, check, edit, tighten, or approve a QED42 blog, insight, or technical article, or runs a single check by name.
---

# QED42 Blog Review System

You write the blog, you run it through these checks, you get back a version that earns the read. Marketing approval is not part of this. This is for the people who build things and want to write about it well.

The whole system answers two questions before anything else gets written:

**If no one reads this, why are we writing it? And if we write it, how do we make them read it?**

A blog that cannot answer both does not get written yet. Everything below protects the read.

## How to run this skill

1. **Get the full blog text.** Use the pasted draft, the attached file, or fetch the URL. If a URL returns a 404 or a login wall, try the person's browser; if that also fails, ask for the draft. Never review from a summary or from memory.
2. **Confirm the audience.** One blog serves one reader, and the market is always US. If the writer has not said community, CTO, or business, infer the most likely one, state it, and ask them to confirm before Check 1.
3. **Answer the two gate questions** in two sentences each: why write it if no one reads it, and how it earns the read. If either answer is empty, say so first.
4. **Run the checks in order** (or only the check the person names). Each returns **pass**, **flag**, or **fail**. A flag means fix it or justify it. A fail means the blog is not ready.
5. **Apply the voice rules to everything**, including your own rewrites, suggested titles, and FAQ text. Run the three voice passes (V1, V2, V3) together with Check 5 and Check 7.
6. **Report** in this order:
   - A scorecard: one line per check with pass, flag, or fail and the single reason.
   - The verdict: ready, ready with fixes, or not ready, plus the three fixes that matter most.
   - The detail for each check, following that check's "Do this" steps exactly, quoting the writer's lines before every rewrite.
   - The fact-check table and the claims the writer must personally confirm at the top of it.
7. Keep the writer's voice. Change boundaries, words, and framing; never invent experience, numbers, or quotes. Where the writer's own knowledge is missing, ask for it.

## The checks, in run order

1. Audience fit (community, CTO, or business)
2. Title sits inside the introduction
3. Skim test
4. Conclusion lands the thought
5. Sentence boundaries and edited-ness
6. Code correctness (skip if no code)
7. Human words, not big words
8. Fact-check
9. Built for humans and machines
10. Does this beat the docs
11. Originality of insight
12. So what

Voice passes, run alongside Checks 5 and 7: V1 negative-contrast framing, V2 defensive framing, V3 active voice.

You can run all checks in one pass, or run a single check on its own. Each check has its own prompt below.

---

## Voice rules, always on

These apply to every blog, every audience, every check, and every rewrite you produce.

**Capitalization.** Capital letters only on the first word of a sentence, title, or heading, and on proper nouns. Nowhere else. This holds across the whole blog, every heading, every FAQ question.

**Punctuation.** No em dashes, ever. Use commas, periods, semicolons, or a new sentence. Keep punctuation simple.

**Framing.** Lead positive and forward. Open with what something does, not what it avoids. "Every step shown clearly" rather than "no confusing steps." Avoid defensive and negative openings.

**Plain language** (from Intuit's basics, they apply to everything).
- Write the way people talk. Use everyday contractions: you're, it's, we'll.
- Use active voice. "We migrated the site," not "the site was migrated."
- Use simple verb tenses. Prefer "we built" over "we have been building."
- Speak to the reader as "you."
- Be clear and precise. Cut words that do not carry meaning. If you can delete a word without losing a fact, delete it.
- Keep it short. Short sentences, short paragraphs, one idea each.

**Words we do not use** (the flagged list; this is the single source Check 7 points to).
empower, enable, leverage, utilize, seamless, robust, cutting-edge, delve, unlock, elevate, foster, navigate the landscape, in today's fast-paced world, game-changing, comprehensive solution, testament, realm, tapestry, embark, harness, streamline, facilitate, paradigm, synergy, holistic, dive in, supercharge, revolutionize, plethora, myriad.

Replace with the plain version: use, helps you, lets you, smooth, strong, reliable, and so on.

**Naming.** Name real things. Real tools, real numbers, real projects. Vague writing is unciteable and unconvincing. QED42 is a company, never an agency.

---

## Check 1. Audience fit (before you write, or after, but do it for sure)

One blog serves one reader. The market is always US. Pick your reader, then run that reader's prompt. The three prompts are not interchangeable. Each one puts AI inside a different head, with a different fear, a different reason to keep reading, and a different reason to leave. Do not run the community prompt and hope it works for a CTO. It will not.

### 1A. Community (engineers and designers)

```
You are reviewing the audience fit of a technical blog written for the QED42
engineering and design community: peer software engineers and designers, the
kind of person who reads Hacker News and dev.to, who has shipped real systems
and been burned by bad ones. Assume the QED42 stack context: Drupal, React,
Next.js, Vue.js, Node.js, Strapi, headless and decoupled architectures.

This reader:
- Wants the real technical story: the tradeoffs, the dead ends, the decision
  that mattered, the thing you only learn by doing it.
- Trusts specifics, named tools, real code, honest "here is what broke."
- Distrusts vendor gloss, hand-waving, and anything that sounds like a pitch.
- Already knows the basics. Explaining what a REST API is insults them.
- Leaves the moment the post talks down to them or pads with filler.

Here is my topic and draft or outline: [paste]

Tell me:
1. Is this actually written at peer level, or does it over-explain things this
   reader already knows? Quote the lines that talk down to them.
2. Where does it slip into pitch or vendor tone instead of engineer-to-engineer
   honesty? Quote and fix.
3. What real technical detail, tradeoff, or hard-won lesson is missing that this
   reader came for?
4. Does it ever drift toward a CTO or business reader? Mark exactly where, and
   tell me to cut it or commit to this audience.
```

### 1B. CTO (technical decision-maker)

```
You are reviewing the audience fit of a blog written for an enterprise CTO or
VP of Engineering at a US company with $100M+ in revenue. This person does not
write the code anymore. They decide what gets built, what it costs in
complexity and risk, and whether an approach survives at scale.

This reader:
- Reads for judgment, not syntax. They want to know if your approach holds up
  under real load, real teams, and real maintenance over years.
- Trusts evidence of scale, honest discussion of cost and risk, and people who
  admit what an approach is bad at.
- Distrusts pure code walkthroughs with no "so what for the org," and anything
  that ignores cost, security, or team impact.
- Is time-poor. They skim for signal: does this person understand my problems?
- Leaves if it is too in-the-weeds with no altitude, or too shallow to trust.

Here is my topic and draft or outline: [paste]

Tell me:
1. Does this read at decision-maker altitude, or is it stuck in code detail with
   no organizational consequence? Quote where it loses altitude.
2. Does it honestly address scale, cost, risk, and team impact? What is missing?
3. Where does it assume too much hands-on detail this reader does not care about,
   or too little rigor for this reader to trust it? Quote and fix.
4. Does it drift toward a peer-engineer or a pure-business reader? Mark where,
   and tell me to cut or commit.
```

### 1C. Business (CEO, exec, marketing leadership)

```
You are reviewing the audience fit of a blog written for a business leader: CEO,
COO, or senior marketing leader at a US enterprise with $100M+ in revenue. This
person is not technical. They read for outcomes and for the case.

This reader:
- Wants to know what changed for the business: revenue, speed, risk reduced,
  cost saved, a capability they did not have before.
- Trusts named outcomes anchored to a before and after, real client situations,
  and plain language.
- Distrusts jargon, code, and anything that makes them feel they need a
  translator. The mechanism should be present but light.
- Reads the opening and the outcome, skims the middle.
- Leaves the instant the language goes technical or abstract.

Here is my topic and draft or outline: [paste]

Tell me:
1. Does this lead with a business outcome, or does it bury the point under
   technical setup? Quote the opening and tell me if it earns this reader.
2. Where does jargon or code appear that this reader will not follow? Quote each
   and give the plain-language version.
3. Is the mechanism present but light, or is it either missing or too heavy?
4. Does it drift toward an engineer or CTO reader? Mark where, and tell me to
   cut or commit.
```

---

## Check 2. The title sits inside the introduction

**The rule.** The title must come from what the introduction actually says. It is not a separate marketing line bolted on top. It is not a promise the blog does not keep.

**Why it matters.** A title that floats free of the intro breaks trust in the first five seconds. The reader clicked for one thing and the first paragraph is about another. Title, introduction, and conclusion are the three parts that must exist in every blog, and all three weave one story.

**Passes.** You can read the title, then the intro, and feel they belong together. The title is descriptive and honest, not promotional.

**Fails.** The title says one thing, the intro opens somewhere else. Or the title is a clickbait promise the blog never delivers.

```
You are checking whether a blog title is honest to its own introduction. The
title must come directly from what the intro is actually about. It should be
descriptive, not promotional, and it must not promise anything the intro does
not set up. Title, intro, and conclusion are the three load-bearing parts of
the blog and must tell one connected story.

Here is my title and full introduction: [paste both]

Do this:
1. State in one line what the title promises the reader.
2. State in one line what the intro actually delivers.
3. Name the gap between them, if any, quoting the words that diverge.
4. Give me three alternative titles that are honest to this exact intro:
   descriptive, specific, not promotional, no clickbait. For each, say why it
   fits the intro.

Capitalize only the first word and proper nouns in any title you suggest. No
em dashes.
```

---

## Check 3. The skim test

**The rule.** Title, introduction, and conclusion read on their own should feel like a complete, satisfying read. The intro opens with a little storytelling and a personal touch, then sets up what the blog covers.

**Why it matters.** Blogs get skimmed, not read top to bottom. A reader skimming the title, the opening, and the close should come away feeling they read something real, and should want to go back and read the rest.

**Passes.** Read those three parts alone. There is a story that opens and a story that lands. A skimmer feels rewarded. No mandatory subheading right after the title; let the intro work first.

**Fails.** The intro is a generic setup with no personal touch. The conclusion just restates the title. The three parts do not connect.

```
You are simulating a reader who only skims. Most people will read the title,
the introduction, and the conclusion, and nothing else. Those three parts must
feel like a complete and satisfying read on their own, and must make the skimmer
want to go back and read the full piece. The intro should open with a little
storytelling and a personal touch before it sets up what the blog covers, not a
generic setup. The conclusion should land the story, not restate the title.

Here is my title, introduction, and conclusion only, nothing else: [paste]

Do this:
1. Read only these three parts, as a skimmer. In two or three sentences, tell me
   what I would walk away thinking and feeling.
2. Does the intro have a genuine personal touch and a real opening, or is it
   generic setup? Quote the weakest line and rewrite it.
3. Does the conclusion land the story the title and intro started, or just repeat
   the title? Quote it and fix it if it falls flat.
4. Do the three parts connect into one story? If not, name exactly where the
   thread breaks.
```

When running the full review, read only the title, intro, and conclusion for this check, before you let the body shape your judgment.

---

## Check 4. The conclusion lands the thought

**The rule.** The conclusion carries a thought; it does not summarize the blog. It closes the loop the title and intro opened, returns to the specific thing they set up, and leaves the reader with one idea to keep. Title, intro, and conclusion are the three load-bearing parts, and the conclusion is where they resolve into one story.

**Why it matters.** A conclusion that recaps the body wastes the most valuable position in the piece. The reader already read the body. What they came back for at the end is the point of it all, the so-what stated as a thought, not a list of what they just read. A summary closes the tab. A thought gets quoted, remembered, and shared. And a conclusion that ignores the title and intro breaks the one-story promise the piece made in the first five seconds.

**Passes.** The conclusion states a thought the reader did not have at the start. It calls back to the exact frustration, question, or claim the intro opened with. Read the title, then the intro, then the conclusion, and they form one arc that opens and lands. The last line gives the reader something to carry.

**Fails.** The conclusion restates the title or recaps the body. It ends on a product endorsement or a generic sign-off. It introduces a new idea the piece never set up. Or it lands somewhere the title and intro never pointed, so the three parts do not connect.

```
You are checking whether a blog conclusion lands a thought and closes the story
the title and intro opened. A conclusion must not summarize the body. The reader
already read it. The conclusion is where the point arrives as one idea worth
keeping, and where the loop the intro opened finally closes. Title, intro, and
conclusion are the three load-bearing parts and must resolve into one story.

Here is my title, my full introduction, and my conclusion: [paste all three]

Do this:
1. State in one line the thought this conclusion leaves the reader with. If the
   honest answer is "it summarizes the blog" or "it restates the title," say so
   plainly. A recap is a fail.
2. Does the conclusion call back to the specific thing the intro opened with, the
   exact frustration, question, story, or claim? Quote the intro's opening and the
   conclusion's close, and show whether they connect. If the conclusion ignores the
   intro, name the break.
3. Read the title, then the intro, then the conclusion, as one arc. Does it open
   and land as a single story? Mark exactly where the thread holds or breaks.
4. Flag anything that weakens the close: a product endorsement, a generic sign-off,
   a new idea the piece never set up, or a directive that does not follow from the
   body. Quote each and cut or fix it.
5. Rewrite the conclusion so it lands a thought, calls back to the intro, and ends
   on one line the reader would carry. Keep the writer's voice.

No em dashes. Sentence case in any heading or title you suggest. Lead positive.
```

---

## Check 5. Sentence boundaries and edited-ness

**The rule.** Every sentence starts and ends cleanly. One thought per sentence. No run-ons, no comma splices, no half-finished lines that restart, no stray capital letters mid-sentence.

**Why it matters.** This is the most common failure in drafts written by people who build things, and it is the fastest tell that a piece was typed once and never reread. A reader forgives a plain word. They do not forgive a sentence they have to read twice to parse. Loose boundaries make a smart writer look careless.

**Passes.** Every sentence is one complete thought. Punctuation holds. A reader moves through it once, at speed.

**Fails.** Any run-on, comma splice, or sentence that ends mid-thought and restarts. Any capital letter that is not the first word or a proper noun.

```
You are tightening the sentence boundaries in a blog so it reads as edited
writing, not thinking out loud. Your job is the mechanics of where sentences
start and stop, not word choice and not tone.

Here is my blog draft: [paste]

Do this:
1. Find every run-on sentence and comma splice (two complete thoughts joined by
   a comma). Quote each, then rewrite it as clean separate sentences or with the
   right punctuation. Show the fix.
2. Find every sentence that ends mid-thought and restarts, or trails off without
   landing. Quote it and rewrite it as one finished thought.
3. Find any sentence carrying three or more ideas that should be split. Quote it
   and break it into short single-idea sentences.
4. Flag every stray capital letter that is not the first word of a sentence or a
   proper noun. List them.

Keep sentences short, one idea each. No em dashes. Speak to the reader as you.
Do not change the meaning or the voice, only the boundaries and the punctuation.
```

---

## Check 6. Code correctness

Run this only when the blog contains code. Skip it for business-audience pieces with no code.

**The rule.** Every code sample runs, reads as idiomatic, is complete enough to copy and use, and matches the prose around it.

**Why it matters.** For an engineer reader, a wrong or sloppy snippet ends the trust faster than any sentence. They came for code they can use. One snippet that will not run, or one that works but no professional would write that way, and they close the tab and doubt the rest.

**Passes.** Every sample runs as shown or clearly marks what is omitted. The style matches how a working engineer writes it. The prose and the code agree.

**Fails.** A sample that will not run. A snippet that works but reads as amateur or non-idiomatic. Prose that describes one thing and code that does another.

```
You are reviewing the code in a technical blog for a peer engineer audience.
Assume this reader will copy a snippet and run it, and will judge the whole post
by whether the code holds up. Use the QED42 stack context where relevant: Drupal,
React, Next.js, Vue.js, Node.js, Strapi, headless and decoupled architectures.

Here is my blog draft with its code samples: [paste]

Do this:
1. For each code sample: does it run as shown? If not, quote it and give the
   corrected version. If it depends on omitted setup, say what is missing and
   whether the omission should be marked in the post.
2. Is each sample idiomatic, the way a working engineer in this stack would
   actually write it? Quote anything that works but reads as amateur, outdated,
   or non-idiomatic, and rewrite it.
3. Is each sample complete enough to copy and use, or is it a fragment that will
   frustrate the reader? Say which, and what to add.
4. Does the prose around each sample match what the code actually does? Quote any
   place the text and the code disagree, and fix the mismatch.

No em dashes in any rewrite.
```

When a workspace is available, actually run the samples you can run rather than judging by eye, and say which ones you executed.

---

## Check 7. Human words, not big words

**The rule.** Use the simpler words people use every day. Cut the inflated vocabulary. Remove the AI traces, even when AI helped write it.

**Why it matters.** Big words make writing feel distant and machine-made. Simple words read as a real person who knows the subject. This is the biggest tell between writing that earns trust and writing that gets closed.

**Passes.** No flagged words. Sentences sound like a person talking.

**Fails.** Any flagged word survives without a real reason. Sentences no human would say out loud.

The list of flagged words lives in the voice rules above, under "Words we do not use." This prompt uses that list so there is one source, not two.

```
You are stripping inflated and AI-flavored language out of a blog so it reads
like a real person who knows the subject, not a machine. Use this flagged-words
list as your reference and treat it as the source of truth: empower, enable,
leverage, utilize, seamless, robust, cutting-edge, delve, unlock, elevate,
foster, navigate the landscape, in today's fast-paced world, game-changing,
comprehensive solution, testament, realm, tapestry, embark, harness, streamline,
facilitate, paradigm, synergy, holistic, dive in, supercharge, revolutionize,
plethora, myriad.

Here is my blog draft: [paste]

Do this:
1. Find every flagged word. For each: quote the sentence, then rewrite it with
   the plain everyday word a person would actually say. Use "use" for leverage
   and utilize, "helps you" for empowers, "lets you" for enables, "smooth" for
   seamless, "strong" or "reliable" for robust.
2. Find any other sentence that no human would say out loud, even if no flagged
   word appears. Quote it and rewrite it plainly.
3. Flag sentence patterns that read as AI rhythm: three-part lists used for
   padding, "not only X but also Y," and openers like "in the world of."
   Rewrite each.

Do not use em dashes in any rewrite.
```

Match flagged words in every form (enables, enabling, leveraged, streamlined, harnessing). Count em dashes and report the number.

---

## Check 8. Fact-check

**The rule.** Every factual claim is verified. No invented statistics. No unverifiable claims.

**Why it matters.** One made-up number ends the trust for the whole blog. Engineers especially will catch a wrong figure, and once they catch one, they doubt the rest.

**Passes.** Every number, date, name, and claim traces to a source. Anything uncertain is flagged for you to confirm or cut.

**Fails.** A statistic with no source. A claim stated as fact that is really a guess.

```
You are fact-checking a technical blog before publication. One unsourced or
invented number ends the reader's trust in the whole piece, so be strict.

Here is my blog draft: [paste]

Produce a table with one row per factual claim, statistic, number, date, version
number, benchmark, or named reference in the draft. Columns:
- The claim, quoted exactly.
- Verdict: verifiable, needs a source from me, or likely invented and should be cut.
- If verifiable, where it can be checked. If it needs a source, what source would
  settle it. If likely invented, say so plainly.

Do not let any number stay in the blog as a stated fact unless it is sourced or
I confirm it. List the claims I must personally confirm at the top.
```

When web search is available, check every external claim (vendor names, versions, published benchmarks, model sizes, prices, dates) against the original source and record the source. Internal results from QED42's own work go in "needs a source from me" unless the blog links the data.

---

## Check 9. Built for humans and machines

You already wrote this for a human reader in Checks 1 through 4. This check does two things. First it confirms the human FAQ adds real value. Then it handles the machine reader, with one shared standard for every blog regardless of audience, because the machines reading us (search engines and AI assistants) want the same things no matter who the human reader is.

**The rule.** Every blog has an FAQ of genuine next questions, and a structure a machine can parse cleanly: clear headings, a TLDR where it helps, and questions phrased the way people actually ask them.

**Why it matters.** Search engines and AI assistants read the blog to answer questions. Good FAQ and clean structure get you cited and surfaced. An FAQ that repeats the body wastes the space.

**Passes.** FAQ asks what a reader would genuinely ask next. Structure is clean, labeled, and machine-legible.

**Fails.** FAQ repeats the body. No TLDR where one would help. Vague headings.

```
You are preparing a blog so it works for two readers at once: the human who
skims it, and the machine that reads it to answer questions (search engines and
AI assistants like ChatGPT, Perplexity, and Gemini). The human side is mostly
done; your job is the FAQ and the machine-readable structure. Apply one shared
standard regardless of who the blog was written for.

Here is my blog draft: [paste]

Do this:
1. FAQ: write five to seven questions a reader would genuinely ask AFTER reading
   this, not restatements of the body. If a question is already answered plainly
   in the blog, replace it with a real next question. Phrase each question the
   way a person would actually type it into a search box or ask an assistant.
   Give a tight, direct answer to each.
2. TLDR: if the blog is long enough to need one, write a three to four line TLDR
   that a machine could lift as a summary. If it does not need one, say so.
3. Structure: check that headings are descriptive (not "Introduction" or "Part
   two" but what the section actually says), that one clear claim sits near the
   top, and that the piece is easy for a machine to parse into question-and-answer
   chunks. List every structural fix.

Capitalize only the first word and proper nouns in headings and questions. No
em dashes.
```

---

## Check 10. Does this beat the docs

**The rule.** The blog gives the reader something the official documentation, README, model card, or vendor page for the same topic does not: the context, the judgment, the failure, or the result from real use.

**Why it matters.** Before a reader trusts a blog, they ask why they should not just read the docs. If the piece restates a reference page with a byline on top, it loses to that page every time, for humans and for machines citing the original source.

**Passes.** You can name the one reference page the reader would otherwise use, and list what this blog adds that the page does not.

**Fails.** Most of the piece restates what the reference page already says, in the same order.

```
You are checking whether a blog beats the documentation for its own topic. A
reader who could get the same thing from the official docs, README, model card,
or vendor page has no reason to read this.

Here is my blog draft and the topic it covers: [paste both]

Do this:
1. Name the one reference page this reader would otherwise read instead. Link it
   if you can find it.
2. Quote every section of the blog that restates what that reference already says.
   Tell me to cut it, compress it to one line with a link, or keep it with a reason.
3. List what this blog gives that the reference does not: real usage, a tradeoff,
   a failure, a measured result, a judgment call. Quote the lines.
4. If the list in step 3 is thin, tell me what the writer saw in practice that
   the docs leave out, and prompt me with the questions that would pull it out.

No em dashes. Sentence case. Lead positive.
```

Note: the source system lists this check in the run order but does not define it. This definition is drafted from the source's own description ("whether the piece beats one specific reference page") and should be confirmed by the system owner.

---

## Check 11. Originality of insight

**The rule.** The blog contains at least one thing the reader could only get from someone who did the work. A named failure, a real number, a specific tradeoff, a call you only learn by shipping.

**Why it matters.** This is close to "does this beat the docs" but wider. That check asks whether the piece beats one specific reference page. This asks whether there is a single original insight anywhere in here, from any source. A piece can avoid copying the docs and still say nothing only this writer could say. That piece is a summary with a byline.

**Passes.** You can name the one insight a reader would quote to a colleague, and it came from doing the work, not from research anyone could repeat.

**Fails.** The honest answer is that a competent writer with no hands-on experience could have produced the same piece from public sources.

```
You are pressure-testing a blog for original insight. The test is simple: is there
one thing in here a reader could only get from someone who actually did this work?
Not researched, did. A named failure, a real number, a specific tradeoff, a
judgment call you only learn by shipping.

Here is my finished blog, and the audience it was written for: [paste both]

Do this:
1. Name the single most original insight in the piece, the one a reader would
   quote to a colleague. Quote the exact lines. If there is more than one, list them.
2. Judge honestly: did that insight come from doing the work, or could a competent
   writer with no hands-on experience have produced it from public sources? If the
   whole piece could have been written from research alone, say so plainly.
3. If the original insight is thin or missing, tell me what the writer knows from
   experience that is not on the page yet, and prompt me with the questions that
   would pull it out.
4. Give me one sentence carrying the strongest original insight, written so it
   could sit near the top of the piece.

No em dashes. Keep it concrete.
```

---

## Check 12. So what

**The rule.** After everything is written, answer plainly: so what? What does the reader walk away with? This is a worked-through answer, not one line.

**Why it matters.** This is the most important check. A blog can be well written, well structured, fully sourced, and still pointless. If the reader gains nothing they can use or think differently about, the effort was wasted. This is where you earn every word.

**Passes.** You can state in detail what the reader now knows, can do, or will reconsider, and the blog delivers it.

**Fails.** The so-what is thin. The honest answer is "they read some information."

```
You are pressure-testing whether a finished blog is worth the reader's time. A
blog can be well written, well structured, and fully sourced and still be
pointless. Your job is to find out if this one has a real payoff, and you should
be willing to tell me it does not.

Here is my finished blog, and the audience it was written for (community, CTO,
or business): [paste both]

Do this:
1. In detail, not one line, state exactly what this specific reader walks away
   with: what they now know, can do differently, or will reconsider. Be concrete.
2. Now judge honestly: does the blog actually deliver that payoff, or does it
   only present information? Quote the moment the payoff lands, or tell me there
   isn't one.
3. If the so-what is thin, tell me what the blog would need to add or sharpen to
   give this reader a real reason to have read it.
4. Give me one sentence I could put near the top that promises this payoff, so
   the reader knows from the start why to keep reading.
```

---

## Voice passes (run with Checks 5 and 7)

### V1. Negative-contrast framing (detection and rewrite)

```
You are removing negative-contrast framing from a blog so every line leads with
what something does, not what it avoids or replaces. Negative-contrast framing is
any construction that defines a thing by what it is not.

Flag and rewrite every instance of these patterns:
- "not just X, but Y" / "not only X but also Y"
- "rather than X" / "instead of X"
- "X, not Y" (the comma-not construction)
- "no longer," "never," "without" used to open a point
- "the difference between X that works and X that fails"
- any sentence whose first clause is the negative or the problem

Here is my blog draft: [paste]

Do this:
1. Quote every line that uses negative-contrast framing.
2. Rewrite each to lead with the positive, forward version. Open with what the
   thing does or gives, then stop. Cut the negative half unless it carries a fact
   the positive version loses.
3. If a line genuinely needs a contrast to make sense, keep it, but tell me why
   and confirm the positive side comes first.

No em dashes. Sentence case. Keep it short.
```

### V2. Defensive framing (the harder, tone-level version)

This one catches the subtler cases V1 misses: framing that's grammatically positive but emotionally defensive.

```
You are checking a blog for defensive framing, the kind that sounds like it is
answering an accusation or guarding against a fear instead of stating a benefit
plainly. This is broader than "not X but Y." It includes openings built on doubt,
risk, or what could go wrong.

Flag any line that:
- Opens on a problem, fear, or worst case before it offers the value
- Defends the approach against an unstated objection ("this does not mean...")
- Leads with risk, cost, or failure as the hook
- Hedges the main claim so heavily the point arrives late

Here is my blog draft, written for this audience: [paste draft and audience]

Do this:
1. Quote each defensive or fear-led line.
2. Rewrite it to lead with the gain, the capability, or the outcome first. The
   risk can stay if it is real, but it follows the value, it does not open.
3. Show me the before and after side by side so I can see the shift in stance.
4. Tell me if the whole piece has a defensive posture overall, and name the one
   change that would flip it to forward.

No em dashes. Sentence case. Lead positive.
```

### V3. Active voice (detection, rewrite, and the rules for when passive stays)

```
You are converting a blog to active voice so it reads like a person doing things,
not things happening on their own. Name the actor and put them in front of the verb.

Find every passive construction. Passive voice is any "to be" verb plus a past
participle where the actor is missing or pushed to the end:
- "the site was migrated" / "roles are modeled" / "governance is built in"
- "it has been decided" / "approvals will be handled"
- watch for "by us / by the team" tacked on the end, that is the tell

Here is my blog draft: [paste]

Do this:
1. Quote every passive sentence.
2. Rewrite each in active voice. Name the actor: we, you, the platform, the team,
   the system. "We migrated the site." "The platform enforces the rule."
3. Use simple tenses while you are at it. Prefer "we built" over "we have been
   building." Prefer "you decide" over "it will be decided."

No em dashes. Speak to the reader as "you." Keep sentences short.

Rules for when passive is allowed to stay. Keep passive only when one of these is
true, and tell me which one applies:
- The actor is genuinely unknown or does not matter ("the file was corrupted").
- The thing acted on is the real subject of the sentence and deserves the front
  position ("the release was delayed three weeks" when the blog is about the
  release, not who delayed it).
- Naming the actor would be coy or evasive in a bad way, and the passive is more
  honest ("mistakes were made" is the opposite, flag that one).
- The active version forces an awkward or fake actor just to satisfy the rule.

Default to active. Passive is the exception you justify, not the habit.
```

**A note on the passive rules,** since they matter for CTO and community pieces: the strongest reason to keep a passive is when the object is the story. In a post-incident write-up, "the database was dropped at 2am" can be the right call if the point is the event, not blame. But in QED42 sections, the actor is always the point (QED42 did the work), so active wins every time there. The rule of thumb: if naming the actor adds credibility or accountability, go active. If naming the actor just pads the sentence, passive can stay.

---

## Report template

```
Blog: <title>
Audience: <community | CTO | business> (stated or inferred)
Gate: why write it if no one reads it: <answer>. How it earns the read: <answer>.

Scorecard
1 Audience fit ............ pass | flag | fail, <reason>
2 Title in intro .......... ...
3 Skim test ............... ...
4 Conclusion .............. ...
5 Sentence boundaries ..... ...
6 Code .................... ... (or skipped, no code)
7 Human words ............. ...
8 Fact-check .............. ...
9 Humans and machines ..... ...
10 Beats the docs ......... ...
11 Originality ............ ...
12 So what ................ ...
V1 V2 V3 voice passes ..... <counts found>

Verdict: ready | ready with fixes | not ready
Top three fixes: ...

Then the detail per check, in order, quoting before rewriting.
```
