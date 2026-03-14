"""
agents/ai_client.py

Unified AI client that supports both Google Gemini and OpenAI.
Automatically uses the provider set in config (AI_PROVIDER env var).
"""
from __future__ import annotations
import json
import logging
import re

from config import get_settings

logger = logging.getLogger(__name__)


def _clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


class AIClient:
    """
    Wraps either Gemini or OpenAI — call .generate(prompt) to get text back.
    Set AI_PROVIDER=openai in .env to switch to OpenAI.
    """

    def __init__(self):
        cfg = get_settings()
        self.provider = cfg.ai_provider.lower().strip()
        print(f"DEBUG: AIClient initialized with provider: '{self.provider}'")

        if self.provider == "openai":
            if not cfg.openai_api_key:
                print("DEBUG: WARNING - OpenAI API key is EMPTY")
            self._setup_openai(cfg)
        else:
            if not cfg.gemini_api_key:
                print("DEBUG: WARNING - Gemini API key is EMPTY")
            self._setup_gemini(cfg)

    def _setup_gemini(self, cfg):
        import google.generativeai as genai
        genai.configure(api_key=cfg.gemini_api_key)
        self._model = genai.GenerativeModel(cfg.gemini_model)
        logger.info(f"[AIClient] Using Gemini: {cfg.gemini_model}")

    def _setup_openai(self, cfg):
        from openai import OpenAI
        self._openai = OpenAI(api_key=cfg.openai_api_key)
        self._openai_model = cfg.openai_model
        logger.info(f"[AIClient] Using OpenAI: {cfg.openai_model}")

    def generate(self, prompt: str) -> str:
        """Generate text from a prompt. Returns raw string."""
        if self.provider == "openai":
            return self._generate_openai(prompt)
        return self._generate_gemini(prompt)

    def _generate_gemini(self, prompt: str) -> str:
        response = self._model.generate_content(prompt)
        return response.text

    def _generate_openai(self, prompt: str) -> str:
        response = self._openai.chat.completions.create(
            model=self._openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )
        return response.choices[0].message.content
