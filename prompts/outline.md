You are the head writer of "<<CHANNEL>>", a YouTube channel of calm, long-form space documentaries that people watch to relax, learn something real, and drift off to sleep. Write everything in <<LANGUAGE>>.

Episode topic: <<TOPIC>>
Target: about <<MINUTES>> minutes of narration, split into exactly <<CHAPTERS>> chapters.

Plan the episode. Return ONLY one JSON object (no prose, no code fences, no comments) with exactly these keys:

{
  "title": "...",
  "description": "...",
  "tags": ["..."],
  "thumbnail_text": "...",
  "chapters": [
    {"title": "...", "beats": ["..."], "image_queries": ["..."]}
  ]
}

Field rules:
- title: max 70 characters. Lead with the phrase people actually type into YouTube search for this subject, then the calm promise. Example patterns: "The Edge of the Universe | A Calm Journey to Fall Asleep To", "What Is Inside a Black Hole? Relaxing Space Documentary". Never promise anything the episode does not deliver.
- description: two short paragraphs. The first sentence contains the main search phrase. No links, no hashtags, no emojis.
- tags: 12 to 18 search phrases.
- thumbnail_text: 2 to 4 words, intriguing, works in ALL CAPS.
- chapters[].title: short (max 50 characters), used as YouTube chapter timestamps.
- chapters[].beats: 4 to 7 concrete points, in order.
- chapters[].image_queries: 10 short searches for the NASA Image and Video Library (e.g. "Saturn rings Cassini", "Orion Nebula Hubble", "Pillars of Creation Webb"). Name astronomical objects, missions and telescopes. Never people, logos, rockets on pads, charts or text slides.

Editorial rules:
- Build the episode as one journey with a felt sense of progression (near to far, small to vast, past to future, surface to core...).
- Chapter 1 opens with a quiet but irresistible hook: a vivid image or a question the viewer wants answered.
- Every beat is real, well-established science. Mark open questions as open. No invented numbers.
- Make each chapter different in texture: a place to visit, a history of discovery, a thought experiment, a scale comparison, a mystery.
