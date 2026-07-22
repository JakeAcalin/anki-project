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
                            "description": "The front of the card: a focused, unambiguous question.",
                        },
                        "answer": {
                            "type": "string",
                            "description": "A concise, direct answer (1-2 sentences).",
                        },
                        "explanation": {
                            "type": "string",
                            "description": (
                                "A detailed explanation for the answer side, written in HTML "
                                "using only <p>, <ul>, <li>, <b>, <i>, <br> tags. Cover the "
                                "reasoning, context, and any nuances a learner needs."
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
                        "media_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "IDs (from the provided media manifest) of images that should "
                                "be shown on the answer side because they directly help explain "
                                "this card. Omit if no image is relevant."
                            ),
                        },
                    },
                    "required": ["question", "answer", "explanation", "tags"],
                },
            }
        },
        "required": ["cards"],
    },
}


def generate_cards(
    *,
    context_text: str,
    media_manifest: List[Dict[str, str]],
    subject_hint: Optional[str],
    instructions: Optional[str],
    max_cards: int,
) -> List[Dict[str, Any]]:
    client = _get_client()

    manifest_text = "\n".join(
        f"- id={m['id']}: {m.get('caption', '(no caption)')}" for m in media_manifest
    ) or "(no images available)"

    prompt_parts = [
        "You are building a hierarchically-tagged Anki deck from study material.",
        "Read the SOURCE MATERIAL below and produce high-quality flashcards.",
        "",
        "Rules:",
        f"- Produce at most {max_cards} cards, prioritizing the most important, testable concepts.",
        "- Each card must be atomic: one question, one clear answer.",
        "- The 'explanation' field is the detailed answer-side writeup: give real depth "
        "(mechanism, context, common misconceptions, examples), not a restatement of the answer.",
        "- Assign hierarchical tags with '::' (e.g. Topic::Subtopic::Detail). Reuse the same "
        "top-level tag across related cards so the deck organizes into a clean tree.",
        "- Only attach media_ids when an image genuinely clarifies that specific card's answer.",
    ]
    if subject_hint:
        prompt_parts.append(f"- Root all tags under the subject '{subject_hint}' where sensible.")
    if instructions:
        prompt_parts.append(f"- Additional instructions from the user: {instructions}")

    prompt_parts += [
        "",
        "AVAILABLE MEDIA:",
        manifest_text,
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
