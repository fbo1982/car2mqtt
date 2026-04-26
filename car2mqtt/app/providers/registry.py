from __future__ import annotations

from app.providers.base import BaseProvider
from app.providers.bmw_provider import BmwProvider
from app.providers.gwm_provider import GwmProvider
from app.providers.acconia_provider import AcconiaProvider
from app.providers.vag_provider import VagProvider, VagBrandProvider
from app.providers.hyundai_provider import HyundaiProvider
from app.providers.mg_provider import MgProvider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, BaseProvider] = {
            "bmw": BmwProvider(),
            "gwm": GwmProvider(),
            "acconia": AcconiaProvider(),
            "hyundai": HyundaiProvider(),
            "mg": MgProvider(),
            "vw": VagBrandProvider("vw"),
            "vwcv": VagBrandProvider("vwcv"),
            "audi": VagBrandProvider("audi"),
            "skoda": VagBrandProvider("skoda"),
            "seat": VagBrandProvider("seat"),
            "cupra": VagBrandProvider("cupra"),
            # Kompatibilität für Fahrzeuge aus v1.1.82; wird nicht mehr in der UI angeboten.
            "vag": VagProvider(),
        }

    def all(self):
        return [provider.descriptor() for key, provider in self._providers.items() if key != "vag"]

    def get(self, provider_id: str) -> BaseProvider:
        if provider_id not in self._providers:
            raise KeyError(f"Unbekannter Provider: {provider_id}")
        return self._providers[provider_id]
