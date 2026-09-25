# Illinois SB 315: what it says, and how it relates to this project

Summarized on 2026-09-22 from published law-firm analyses (sources below), not from
the enrolled bill text. Points marked *unconfirmed* should be checked against the bill
on [ilga.gov](https://www.ilga.gov/) before being relied on. This is not legal advice.

## Facts

- **Name:** Artificial Intelligence Safety Measures Act, **SB 315**. Signed by
  Gov. Pritzker **July 6, 2026**. Illinois is the third state with a frontier-AI safety
  law, after California and New York.
- **Effective:** the Act takes effect **Jan 1, 2027**. The headline compliance
  obligations — a published "Frontier AI Framework" and an **independent third-party
  audit** — apply from **Jan 1, 2028**. *Unconfirmed:* whether incident reporting
  starts in 2027 or 2028; sources summarize it without pinning the date.
- **Who it covers:** *frontier developers* = companies that **train** a model using
  more than 10^26 operations; *large frontier developers* = those with **> $500M**
  annual gross revenue. It regulates model **developers**, not companies that deploy
  or build on someone else's model.
- **Incident reporting:** report a *critical safety incident* to the Illinois
  Emergency Management Agency and the Attorney General **within 72 hours** of learning
  of it; **within 24 hours** (and to any law-enforcement / public-safety agency with
  jurisdiction) if there is imminent risk of death or serious physical injury.
- **"Critical safety incident"** covers: unauthorized access to / modification of
  model weights; harm from a catastrophic risk; loss of control of a frontier model
  causing death or injury; a frontier model using deceptive techniques to subvert the
  developer's own safety measures.
- **Enforcement:** Attorney General only (no private right of action); up to **$1M**
  for a first violation, **$3M** for subsequent ones.

## How it relates to this project

- Companies that build agents on top of these models are **not** covered by SB 315,
  and an agent overspending or attempting `rm -rf` is **not** a "critical safety
  incident" under the Act.
- The incident export is therefore an **incident-style report modeled on the 72-hour
  timeline**, not a regulatory filing, and this project makes no claim of SB 315
  compliance.
- The relevance is indirect: SB 315 (like similar laws in California and New York)
  raises expectations for audit-ready records across the AI supply chain, and
  enterprise customers increasingly ask deployers the same questions.

## Sources

- [Crowell & Moring — What Frontier AI Developers Must Do Before January 2028](https://www.crowell.com/en/insights/client-alerts/illinois-imposes-transparency-and-safety-obligations-on-frontier-ai-systems)
- [McDonald Hopkins — Overview of the Act](https://www.mcdonaldhopkins.com/insights/news/illinois-artificial-intelligence-safety-measures-act)
- [Skadden — first state to mandate third-party audits](https://www.skadden.com/insights/publications/2026/07/illinois-enacts-ai-safety-law-becoming-first-state)
- [Greenberg Traurig](https://www.gtlaw.com/en/insights/2026/7/illinois-enacts-artificial-intelligence-safety-measures-act)
- [National Law Review](https://natlawreview.com/article/illinois-enacts-artificial-intelligence-safety-measures-act)
- [Norton Rose Fulbright](https://www.nortonrosefulbright.com/en-us/knowledge/publications/68f0462c/illinois-enacts-artificial-intelligence-safety-measures-act)
- [Gov. Pritzker press release](https://gov-pritzker-newsroom.prezly.com/gov-pritzker-signs-nation-leading-artificial-intelligence-safety-law)
