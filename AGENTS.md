# ultraloom

## Where things live

Specs, plans and SDD live under `docs/.superpowers/`. Flows, each with its
graph picture and an explanation, live under `docs/abläufe/`.

## Languages

Anything that instructs an LLM is written in English: this file, `CLAUDE.md`,
and whatever lives under `.claude/`. A model reads them on every turn, and a
second language in the file it steers by buys nothing.

The documentation is bilingual instead: the file without a suffix is the
English variant and the standard, the German one carries `.de.md` right beside
it — `README.md` / `README.de.md`, `docs/abläufe/verify-until-green.md` /
`verify-until-green.de.md`. Each variant links to the other under its heading.

Exempt from both rules are the working papers under `docs/.superpowers/`: specs
and plans are written once, read by a human, and never translated.
