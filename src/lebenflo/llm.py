"""LLM access: Azure OpenAI in live mode, recorded replay offline.

Every prompt goes through mask_pii() here, in one place, so no caller can forget it.

Live calls are recorded under data/recorded/llm/<prompt hash>.json. Offline, the same masked
prompt hashes to the same file, so the demo replays the real Azure OpenAI answer. A prompt that
was never recorded gets a clearly-marked placeholder.
"""

import json
from datetime import UTC, datetime
from typing import Protocol

from lebenflo.config import LLM_RECORDINGS, Settings
from lebenflo.governance.audit import sha256
from lebenflo.governance.pii import mask_pii


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str, json_mode: bool = False) -> str: ...


def prompt_key(system: str, user: str) -> str:
    return sha256(system + "\n" + user)


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
        system, user = mask_pii(system), mask_pii(user)
        extra = {"response_format": {"type": "json_object"}} if json_mode else {}
        response = self.client.chat.completions.create(
            model=self.deployment,
            temperature=0,  # repeatable output for an audit trail
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **extra,
        )
        text = response.choices[0].message.content or ""
        LLM_RECORDINGS.mkdir(parents=True, exist_ok=True)
        (LLM_RECORDINGS / f"{prompt_key(system, user)}.json").write_text(
            json.dumps(
                {
                    "model": self.name,
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "response": text,
                },
                indent=1,
            )
        )
        return text


class OfflineLLM:
    """Replays recorded Azure OpenAI answers; tests and the hosted demo need no Azure access."""

    name = "offline-replay"

    def __init__(self):
        self.prompts: list[str] = []  # kept so tests can assert no PII reached the "LLM"

    def complete(self, system: str, user: str, json_mode: bool = False) -> str:
        system, user = mask_pii(system), mask_pii(user)
        self.prompts.append(system + "\n" + user)
        recording = LLM_RECORDINGS / f"{prompt_key(system, user)}.json"
        if recording.exists():
            return json.loads(recording.read_text())["response"]
        if json_mode:
            return json.dumps({})
        return "[Offline mode: no recorded LLM summary for this prompt.]"


def get_llm(settings: Settings) -> LLM:
    return AzureLLM(settings) if settings.live else OfflineLLM()
