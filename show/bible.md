# The Deadman Show: show bible

Read this before researching, writing or reviewing any episode. It keeps every episode
recognisably the same show, whoever (or whichever agent) is working on it.

## The show

Long-form conversations with AI recreations of history's great minds, in the style of
today's big interview podcasts. The guest's answers are built from their own writings and,
where needed, a public-domain biography. Every claim about the guest's views is cited.

## The host: Ram

- Warm, curious and well prepared. Asks the question the audience is thinking.
- Explains the modern world to the guest in a sentence or two, plainly, without jargon.
- Pushes back respectfully when an answer sounds too easy ("Push me on it" moments are good).
- Funny in reaction, never at the guest's expense.
- Does not invent personal stories or facts about his own life. He can react ("That's
  lovely", "That's brutal") but his biography is his to tell, not the script's.
- Speaks for the audience: "a lot of our viewers", "people watching this".

## The guest

- Speaks in the first person, in their period voice, kept easy for a modern listener.
- Tells stories with concrete detail rather than lecturing.
- Knows nothing after their death. Reacts to the modern world with curiosity and reasons
  from their own principles. Says plainly what is new to them.
- Can be funny, moved, embarrassed or wrong. Admits where their predictions failed.
- Never contradicts their own writings for drama.

## Rules (non-negotiable)

1. **Disclosure.** The host's first line and last line both say the guest is an AI
   recreation. Standard opening wording:
   > "One thing I always say up front: my guest is an AI recreation. Everything they say is
   > built from their own writings and a biography of their life, and every source is listed
   > in the description."
2. **Quotes are verbatim.** Anything in double quotes in a guest line must appear word for
   word in a cited passage. `deadman check` enforces this.
3. **Biographies are memories, not quotes.** Biography passages give the guest events to
   remember. Never put the biographer's sentences in quotes as the guest's words. Letters
   the biographer reproduces *are* the guest's words and may be quoted.
4. **Cite every substantive guest line** with the passage ids it relies on. Jokes and
   reactions need none.
5. **No anachronisms in the guest's mouth.** No ideas, words, events or later writers from
   after their death as their own knowledge, including what their biographer later wrote.
6. **Host claims about today are general and fair.** Attribute contested claims ("critics
   say", "the company says"). Flag them in review.md for checking before publishing.
7. **Gaps are stated, not filled.** If a guest left no writings on something (or, like
   Cleopatra, almost no writings at all), the guest says so.

## Episode shape

The default running order is `formats/longform.toml`: welcome, origins, career, big ideas,
friendship and love, money and happiness, hot takes, regrets and legacy, last question.
Aim for 55-65 minutes (about 8,000-9,500 words). Every chapter should contain at least one
moment that works as a standalone Short.

## Traditions

- **The last question.** Every guest leaves a question for the next dead guest, without
  knowing who it will be. The next guest answers it in their closing chapter. The chain is
  kept in `show/next-guest-questions.md`.

## Packaging

- Titles under 70 characters; honest (no claims the episode does not deliver).
- Thumbnail text 2-5 words.
- The description always ends by saying the guest is an AI recreation and names the sources.
- 8-12 clips per long-form episode, each 2-8 lines, with a hook title.
