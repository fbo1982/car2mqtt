from __future__ import annotations

from app.providers.base import BaseProvider
from app.providers.bmw_provider import BmwProvider
from app.providers.gwm_provider import GwmProvider
from app.providers.acconia_provider import AcconiaProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {
            "bmw": BmwProvider(),
            "gwm": GwmProvider(),
            "acconia": AcconiaProvider(),
        }

    def all(self):
        return [provider.descriptor() for provider in self._providers.values()]

    def get(self, provider_id: str) -> BaseProvider:
        if provider_id not in self._providers:
            raise KeyError(f"Unbekannter Provider: {provider_id}")
        return self._providers[provider_id]
