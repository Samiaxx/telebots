"""Google Gemini content rewriting.

Goal: output that reads like it was written by someone who actually follows
this source's beat and cares about it — not a generic "rewrite this" bot
pass. We do this by feeding Gemini the source's declared persona/niche (if
set) and by instructing it to write with the specific knowledge, vocabulary,
and framing an insider in that niche would use, rather than a neutral
summary voice.
"""
import logging
import os

import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("telebot.gemini")

# Fallback only — used to seed the database on first run. After that, the
# key stored in Settings (changeable from the admin panel) is what's
# actually used for every call, via the api_key parameter below.
ENV_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

SKIP_TOKEN = "SKIP"

# If the configured model name is wrong, retired, or otherwise rejected by
# Google, fall back to this instead of failing the whole pipeline. This is
# Google's own auto-updating alias for their current flash model, so it
# should stay valid even as specific dated model names get retired over time.
FALLBACK_MODEL = "gemini-flash-latest"

# Maps admin-panel intensity setting to generation params.
INTENSITY_TEMPERATURE = {
    "light": 0.5,
    "heavy": 0.95,
}

BASE_PROMPT = """You are a knowledgeable writer who genuinely follows {beat} closely — this is your beat, not a random assignment. Rewrite the text below in {language} the way a real person immersed in this topic would post about it: informed, specific, and conversational.

Ground rules:
- Do not summarize like a news-wire or a press release. Write like a person sharing something they found genuinely interesting, using the natural vocabulary and framing an insider in this niche would use.
- Vary sentence length and structure the way real writing does. Avoid formulaic openers like "In today's world" or "It's important to note."
- No Markdown, no hashtags, no emoji spam, no "AI assistant" tone, no phrases like "as an AI" or "this article discusses."
- Do not pad with filler or repeat the same point twice. Say what matters and stop.
- Keep it factually faithful to the source text — don't invent facts, numbers, or quotes that aren't there.
{persona_line}
If the text has nothing to do with any of these topics: {keywords}, respond with exactly: SKIP
Only output the rewritten text itself, nothing else — no preamble, no explanation.

Text: {content}"""


def _build_beat_description(keywords: list[str], persona: str | None) -> str:
    if persona:
        return persona.strip()
    if keywords:
        return ", ".join(keywords)
    return "this subject"


def rewrite_content(
    content: str,
    language: str,
    keywords: list[str],
    style: str,
    model_name: str = "gemini-flash-latest",
    persona: str | None = None,
    api_key: str | None = None,
) -> str | None:
    """Rewrite `content` via Gemini. Returns None if Gemini says to skip, or on error."""
    effective_key = api_key or ENV_GEMINI_API_KEY
    if not effective_key:
        logger.error("No Gemini API key configured (Settings or GEMINI_API_KEY); cannot rewrite content.")
        return None

    genai.configure(api_key=effective_key)

    keyword_str = ", ".join(keywords) if keywords else "any topic (no restriction)"
    beat = _build_beat_description(keywords, persona)
    persona_line = (
        f"- Voice/persona to write in: {persona.strip()}" if persona and persona.strip() else ""
    )

    prompt = BASE_PROMPT.format(
        language=language,
        beat=beat,
        keywords=keyword_str,
        persona_line=persona_line,
        content=content,
    )

    temperature = INTENSITY_TEMPERATURE.get(style, 0.5)
    generation_config = genai.types.GenerationConfig(temperature=temperature)

    result = _call_gemini(model_name, prompt, generation_config)

    if result is None and model_name != FALLBACK_MODEL:
        # Likely an invalid/retired model name (a 404 "model not found" style
        # error). Retry once with the known-good fallback rather than giving
        # up — this is what keeps a stale Settings value from silently
        # blocking every single post.
        logger.warning(
            "Gemini call with model '%s' failed; retrying once with fallback model '%s'.",
            model_name, FALLBACK_MODEL,
        )
        result = _call_gemini(FALLBACK_MODEL, prompt, generation_config)

    if result is None:
        return None

    if result == SKIP_TOKEN or result.strip().upper() == SKIP_TOKEN:
        return None

    return result


def _call_gemini(model_name: str, prompt: str, generation_config) -> str | None:
    """Single attempt at calling Gemini. Returns the raw text, or None on any failure."""
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(prompt, generation_config=generation_config)
        return (response.text or "").strip()
    except Exception as exc:  # noqa: BLE001 - external API, keep bot alive on any failure
        logger.error("Gemini call failed (model=%s): %s", model_name, exc)
        return None
