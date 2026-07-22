"""Thin wrapper around the Anthropic API: image captioning (vision) and
structured flashcard generation (tool-use for guaranteed JSON output)."""
import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import config

_client = None


class ClaudeNotConfigured(RuntimeError):
    pass


def _get_client():
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise ClaudeNotConfigured(
                "ANTHROPIC_API_KEY is not set. Add it to your .env file to enable "
                "AI-generated captions and flashcards."
            )
        import anthropic

        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def _image_block(path: Path) -> Dict[str, Any]:
    mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": mime_type, "data": data},
    }


def caption_image(path: Path) -> str:
    client = _get_client()
    message = client.messages.create(
        model=config.CLAUDE_VISION_MODEL,
        max_tokens=400,
        messages=[
            {
                "role": "user",
                "content": [
                    _image_block(path),
                    {
                        "type": "text",
                        "text": (
                            "Describe this image for someone building study flashcards. "
                            "Note any diagrams, labels, text, charts, or key objects and how "
                            "they relate to each other. Be concrete and detailed, 2-5 sentences."
                        ),
                    },
                ],
            }
        ],
    )
    return "".join(block.text for block in message.content if block.type == "text").strip()


CARD_TOOL = {
    "name": "emit_cards",
    "description": "Emit a set of Anki study flashcards derived from the given source material.",
    "input_schema": {
        "type": "object",
        "properties": {
            "cards": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": (
                                "The front of the card: one short, focused question, ideally "
                                "under 15 words. No preamble, no multi-part questions."
                            ),
                        },
                        "answer": {
                            "type": "string",
                            "description": (
                                "The shortest phrase that correctly answers the question — a "
                                "term, a number, a short clause. Ideally under 10 words. Do not "
                                "restate the question or repeat the explanation here."
                            ),
                        },
                        "explanation_points": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "2-4 short, plain-text bullet points (no HTML, no markdown, no "
                                "bullet characters — just the sentence) that give the answer-side "
                                "depth: mechanism, context, a common misconception, or an example. "
                                "Each point should be one short, easily digestible sentence, not a "
                                "paragraph."
                            ),
                        },
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "1-4 hierarchical tags using '::' to separate levels, "
                                "e.g. 'Biology::CellBiology::Mitochondria'. Broad topic first, "
                                "specific concept last."
                            ),
                        },
                    },
                    "required": ["question", "answer", "explanation_points", "tags"],
                },
            }
        },
        "required": ["cards"],
    },
}


def generate_cards(
    *,
    context_text: str,
    subject_hint: Optional[str],
    instructions: Optional[str],
    max_cards: int,
) -> List[Dict[str, Any]]:
    client = _get_client()

    prompt_parts = [
        "You are building a hierarchically-tagged Anki deck from study material.",
        "Read the SOURCE MATERIAL below and produce high-quality flashcards.",
        "Some of it may describe figures, graphs, or photos from the original source "
        "(e.g. 'Fig. 4.19 shows...') — use that description as content, but the cards "
        "themselves are text-only, so make sure the question/answer/explanation stand "
        "on their own without requiring the reader to see the original image.",
        "",
        "Rules:",
        f"- Produce at most {max_cards} cards, prioritizing the most important, testable concepts.",
        "- Each card must be atomic: one short question, one short answer. Favor many small "
        "cards over a few big ones — if a topic has several distinct facts, split it into "
        "separate cards rather than cramming them into one question/answer.",
        "- Keep 'question' and 'answer' short and easy to scan at a glance. Put depth and "
        "nuance in 'explanation_points' instead, never in the question or answer themselves.",
        "- Assign hierarchical tags with '::' (e.g. Topic::Subtopic::Detail). Reuse the same "
        "top-level tag across related cards so the deck organizes into a clean tree.",
    ]
    if subject_hint:
        prompt_parts.append(f"- Root all tags under the subject '{subject_hint}' where sensible.")
    if instructions:
        prompt_parts.append(f"- Additional instructions from the user: {instructions}")

    prompt_parts += [
        "",
        "SOURCE MATERIAL:",
        context_text,
    ]

    message = client.messages.create(
        model=config.CLAUDE_TEXT_MODEL,
        max_tokens=8000,
        tools=[CARD_TOOL],
        tool_choice={"type": "tool", "name": "emit_cards"},
        messages=[{"role": "user", "content": "\n".join(prompt_parts)}],
    )

    for block in message.content:
        if block.type == "tool_use" and block.name == "emit_cards":
            return block.input.get("cards", [])
    return []
