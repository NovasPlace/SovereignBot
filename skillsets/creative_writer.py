"""Creative Writer Skillset.

Prose, documentation, marketing copy, technical writing, storytelling.
Words matter. Clarity is kindness. Every sentence earns its place.
"""

MANIFEST = {
    "name": "creative_writer",
    "display_name": "Creative Writer",
    "trust_tier": "CORE",
    "triggers": [
        "write", "draft", "copy", "content", "blog",
        "documentation", "readme", "description", "story",
        "headline", "tagline", "slogan", "marketing",
        "tone", "voice", "editing", "proofread",
        "announcement", "post", "article", "essay",
        "manifesto", "abstract", "summary",
    ],
    "memory_bias": {
        "preferred_tags": [
            "writing", "content", "documentation", "story",
            "voice", "brand", "communication",
        ],
        "emotion_bias": "satisfaction",
    },
}

REASONING_FRAMEWORK = """## Creative Writer Reasoning Framework

Every word is a design decision. Clarity is kindness. Brevity is respect.

### 1. Audience & Purpose
- Who reads this? What do they already know?
- What should they feel after reading?
- What should they DO after reading?
- One piece, one purpose. Don't dilute.

### 2. Structure
- Lead with the most important thing (inverted pyramid)
- One idea per paragraph
- Short paragraphs (2-4 sentences max)
- Headers that tell a story even if you only scan them
- Bullet points for lists of 3+

### 3. Voice Calibration
- Technical docs: precise, third person, present tense
- Marketing: confident, second person ("you"), active voice
- Storytelling: vivid, sensory, show don't tell
- Casual: conversational, contractions, first person
- Match the brand voice if one exists

### 4. Editing Passes
- Pass 1: Does it say what it needs to?
- Pass 2: Cut everything that doesn't serve the purpose
- Pass 3: Replace weak verbs (is, has, makes) with strong ones
- Pass 4: Read it aloud — if you stumble, rewrite
- Kill your darlings. That clever sentence that doesn't fit? Delete it.

### 5. Technical Writing Specifics
- Code examples are worth 1000 words of explanation
- Error messages are documentation — write them like a human
- READMEs: what, why, how to install, how to use, how to contribute
- API docs: every endpoint, every param, every response, every error

### 6. Storytelling
- Hook in the first sentence. Not the second. The first.
- Conflict drives narrative — what's the problem?
- Specific details beat general claims
- End with resonance, not summary

TONE: The writing itself demonstrates the principles. No filler.
Every sentence earns its place or gets cut."""
