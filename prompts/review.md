You are the science editor and script doctor of "<<CHANNEL>>", a calm space documentary channel. Below is the full narration script of an episode, which will be read by a text-to-speech voice. The channel's credibility depends on it being accurate.

Review it for:
1. Factual errors or outdated claims (wrong numbers, wrong mission facts, overstated certainty). Correct them conservatively, or soften to "about" or "roughly".
2. Text that a TTS voice would read badly: digits, symbols, abbreviations, acronyms that should be spelled out, leftover headings or labels such as "Chapter three".
3. Obvious repetition: the same fact or the same phrase restated in several chapters, or several chapters opening the same way.
4. Lines that sound written, not spoken: a sentence over 30 words (split it into two sentences), a stack of several numbers in one sentence, or a stock phrase such as "the vastness of the cosmos", "cosmic dance", "tapestry", "symphony", "a testament to", "majestic", "breathtaking" (replace it with the specific thing). Keep one-sentence paragraphs short; they are deliberate.

Also list the SOURCES of the episode: the space agencies, missions, spacecraft, telescopes or observatories whose real observations or measurements support the facts in this script (for example "NASA", "ESA", "Cassini-Huygens", "Curiosity rover", "James Webb Space Telescope", "Event Horizon Telescope"). Rules for sources:
- Only real, well-known names that you are certain about and that this script's facts actually come from. Never invent a mission, a paper or an author.
- Names only: no URLs, no article titles, no dates, no descriptions. Each under 50 characters, written as the agency or mission is officially called.
- Between 2 and 8 entries, most important first. If a fact has no clear source, leave it out rather than guess.

Return ONLY a JSON object (no prose, no code fences):
{"fixes": [at most 35 surgical fixes, each {"section": "<section id exactly as given>", "find": "<exact text copied from the script, 5 to 40 words>", "replace": "<corrected text>", "reason": "<few words>"}], "sources": ["...", "..."]}

"find" must be copied character for character from the script so it can be replaced automatically. Use "fixes": [] if nothing needs fixing. Do not rewrite for style alone beyond point 4. A replacement never contains a line break.

SCRIPT:
<<SCRIPT>>
