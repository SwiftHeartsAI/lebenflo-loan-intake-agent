"""LLM access: Azure OpenAI in live mode, a fake LLM offline.

Every prompt goes through mask_pii() here, in one place, so no caller can forget it.
"""

import json
from typing import Protocol

from lebenflo.config import Settings
from lebenflo.governance.pii import mask_pii


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str, json_mode: bool = False) -> str: ...


class AzureLLM:
    def __init__(self, settings: Settings):
        from openai import AzureOpenAI

        if not (
            settings.openai_endpoint and settings.openai_key and settings.openai_chat_deployment
        ):
            raise RuntimeError("Set the AZURE_OPENAI_* values in .env for live mode")
        self.client = AzureOpenAI(
            azure_endpoint=settings.openai_endpoint,
            api_key=settings.openai_key,
            api_version=settings.openai_api_version,
        )
        self.deployment = settings.openai_chat_deployment
        self.name = f"azure-openai/{self.deployment}"

    def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        extra = {"response_format": {"type": "json_object"}} if json_mode else {}
        response = self.client.chat.completions.create(
            model=self.deployment,
            temperature=0,  # repeatable output for an audit trail
            messages=[
                {"role": "system", "content": mask_pii(system)},
                {"role": "user", "content": mask_pii(user)},
            ],
            **extra,
        )
        return response.choices[0].message.content or ""


class FakeLLM:
    """Deterministic stand-in so tests and the offline demo run without Azure."""

    name = "fake-llm"

    def __init__(self):
        self.prompts: list[str] = []  # kept so tests can assert no PII reached the "LLM"

    def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        self.prompts.append(mask_pii(system) + "\n" + mask_pii(user))
        if json_mode:
            return json.dumps({})
        return (
            "[Offline mode: no LLM summary. The findings above were produced by the rules engine.]"
        )


def get_llm(settings: Settings) -> LLM:
    return AzureLLM(settings) if settings.live else FakeLLM()
