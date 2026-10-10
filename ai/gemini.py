"""
Google Gemini AI backend.

Uses the google-genai SDK (lightweight, API-key only).
No Vertex AI complexity — one API key and you're done.
"""
import logging
from typing import Optional

from .base import AIBackend

logger = logging.getLogger(__name__)


class GeminiBackend(AIBackend):
    """Google Gemini backend via google-genai SDK."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash",
                 temperature: float = 0.2, max_output_tokens: int = 8192):
        try:
            from google import genai
        except ImportError:
            raise ImportError(
                "google-genai is required for Gemini backend. "
                "Install it with: pip install google-genai"
            )
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens

    def call(self, prompt: str, images: Optional[list] = None, text: Optional[str] = None) -> str:
        """
        Send prompt + optional images/text to Gemini.

        Args:
            prompt: instruction prompt
            images: optional list of PIL.Image objects
            text: optional extracted document text

        Returns:
            raw model response text
        """
        from google.genai import types

        parts = [prompt]

        if images:
            from PIL import Image as PILImage

            for i, img in enumerate(images):
                if not isinstance(img, PILImage.Image):
                    logger.warning(f"Skipping non-PIL image at index {i} (type: {type(img).__name__})")
                    continue
                parts.append(f"--- IMAGE PAGE {i + 1} ---")
                parts.append(img)  # google-genai SDK handles PIL.Image serialization

        if text:
            parts.append(f"--- TEXT CONTENT ---\n{text}")

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=parts,
                config=types.GenerateContentConfig(
                    temperature=self._temperature,
                    max_output_tokens=self._max_output_tokens,
                ),
            )
            return response.text or ""
        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
            raise
