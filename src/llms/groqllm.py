"""Factory for the Groq chat model.

This wraps the LangChain ``ChatGroq`` client so the rest of the app can ask for
"the LLM" without knowing about API keys or model names - those come from the
central :mod:`src.config.settings`.
"""

from langchain_groq import ChatGroq

from src.config import get_settings


class GroqLLM:
    """Builds a configured Groq chat model on demand."""

    def __init__(self):
        # Pull the validated settings (key + model name). If GROQ_API_KEY were
        # missing, this call would already have failed at startup.
        self.settings = get_settings()

    def get_llm(self, tier: str = "fast") -> ChatGroq:
        """Return a ready-to-use Groq chat model for the given tier.

        ``tier="strong"`` selects the higher-quality model (for the main writing
        step); any other value uses the fast default. Raises a clear error (with
        the real underlying cause) if the client cannot be created.
        """
        try:
            return ChatGroq(
                api_key=self.settings.groq_api_key,
                model=(
                    self.settings.groq_model_strong
                    if tier == "strong"
                    else self.settings.groq_model
                ),
                # Blogs are long. Give the model a generous output budget so
                # content and translations are not truncated.
                max_tokens=self.settings.groq_max_tokens,
                # gpt-oss models reason before answering; keep it low so the
                # output budget goes to the actual text, not hidden reasoning.
                reasoning_effort=self.settings.groq_reasoning_effort,
                timeout=self.settings.groq_timeout,
            )
        except Exception as exc:  # noqa: BLE001 - re-raised with context below
            # `from exc` keeps the original error attached for debugging, and
            # the f-string actually interpolates the message (the old code did
            # not, so it printed a literal "{e}").
            raise ValueError(f"Failed to initialise Groq LLM: {exc}") from exc
