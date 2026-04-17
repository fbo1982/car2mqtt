from __future__ import annotations

from typing import Dict
from app.providers.base import BaseProvider
from app.providers.bmw import BmwProvider
from app.providers.gwm import GwmProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: Dict[str, BaseProvider] = {
            "bmw": BmwProvider(),
            "gwm": GwmProvider(),
        }

    def all(self):
        return [provider.descriptor() for provider in self._providers.values()]

    def get(self, provider_id: str) -> BaseProvider:
        if provider_id not in self._providers:
            raise KeyError(f"Unbekannter Provider: {provider_id}")
        return self._providers[provider_id]
