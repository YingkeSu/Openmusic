from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    display_name: str
    api_key_env: str
    base_url_env: str
    default_base_url: str
    default_model: str


@dataclass(frozen=True)
class LLMRuntimeConfig:
    provider_id: str
    model: str
    base_url: str
    api_key: str
    enabled: bool


@dataclass
class LLMConfigRegistry:
    default_provider: str
    providers: dict[str, ProviderSpec]

    @staticmethod
    def load(registry_path: Path) -> "LLMConfigRegistry":
        raw = json.loads(registry_path.read_text(encoding="utf-8"))
        providers: dict[str, ProviderSpec] = {}
        for provider_id, item in raw.get("providers", {}).items():
            providers[provider_id] = ProviderSpec(
                provider_id=provider_id,
                display_name=str(item.get("display_name", provider_id)),
                api_key_env=str(item["api_key_env"]),
                base_url_env=str(item["base_url_env"]),
                default_base_url=str(item["default_base_url"]),
                default_model=str(item["default_model"]),
            )
        default_provider = str(raw.get("default_provider", "deepseek"))
        if default_provider not in providers:
            raise ValueError(f"default provider '{default_provider}' missing in registry")
        return LLMConfigRegistry(default_provider=default_provider, providers=providers)


def parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, value = s.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def resolve_llm_runtime(
    root_dir: Path,
    payload: dict,
    registry: LLMConfigRegistry,
) -> LLMRuntimeConfig:
    env_from_file = parse_dotenv(root_dir / ".env")

    def env_get(name: str) -> str:
        return str(payload.get(name) or os.getenv(name) or env_from_file.get(name) or "").strip()

    provider_id = str(payload.get("ai_provider") or env_get("AI_PROVIDER") or registry.default_provider)
    if provider_id not in registry.providers:
        provider_id = registry.default_provider
    provider = registry.providers[provider_id]

    base_url = (
        str(payload.get("ai_base_url") or "").strip()
        or env_get("AI_BASE_URL")
        or env_get(provider.base_url_env)
        or provider.default_base_url
    )
    model = (
        str(payload.get("ai_model") or "").strip()
        or env_get("AI_MODEL")
        or provider.default_model
    )
    api_key = (
        str(payload.get("ai_api_key") or "").strip()
        or env_get("AI_API_KEY")
        or env_get(provider.api_key_env)
    )

    return LLMRuntimeConfig(
        provider_id=provider.provider_id,
        model=model,
        base_url=base_url,
        api_key=api_key,
        enabled=bool(api_key and base_url and model),
    )
