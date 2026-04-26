from __future__ import annotations

from app.providers.base import BaseProvider
from app.providers.bmw_provider import BmwProvider
from app.providers.gwm_provider import GwmProvider
from app.providers.acconia_provider import AcconiaProvider
from app.providers.vag_provider import VagProvider, VagBrandProvider
from app.providers.hyundai_provider import HyundaiProvider
from app.providers.mg_provider import MgProvider
from app.providers.generic_brand_provider import GenericBrandProvider


class ProviderRegistry:
    def __init__(self) -> None:
        # Reihenfolge entspricht der alphabetischen Anzeige im Hersteller-Dropdown.
        # "vag" bleibt nur als Legacy-Provider erhalten und wird in all() ausgeblendet.
        self._providers: dict[str, BaseProvider] = {
            "acconia": AcconiaProvider(),
            "audi": VagBrandProvider("audi"),
            "bmw": BmwProvider(),
            "byd": GenericBrandProvider("byd"),
            "citroen": GenericBrandProvider("citroen"),
            "cupra": VagBrandProvider("cupra"),
            "gwm": GwmProvider(),
            "hyundai": HyundaiProvider(),
            "kia": GenericBrandProvider("kia"),
            "lucid": GenericBrandProvider("lucid"),
            "mercedes": GenericBrandProvider("mercedes"),
            "mg": MgProvider(),
            "nissan": GenericBrandProvider("nissan"),
            "opel": GenericBrandProvider("opel"),
            "peugeot": GenericBrandProvider("peugeot"),
            "renault": GenericBrandProvider("renault"),
            "seat": VagBrandProvider("seat"),
            "skoda": VagBrandProvider("skoda"),
            "tesla": GenericBrandProvider("tesla"),
            "toyota": GenericBrandProvider("toyota"),
            "volvo": GenericBrandProvider("volvo"),
            "vw": VagBrandProvider("vw"),
            "vwcv": VagBrandProvider("vwcv"),
            # Kompatibilität für Fahrzeuge aus v1.1.82; wird nicht mehr in der UI angeboten.
            "vag": VagProvider(),
        }

    def all(self):
        return [provider.descriptor() for key, provider in self._providers.items() if key != "vag"]

    def get(self, provider_id: str) -> BaseProvider:
        if provider_id not in self._providers:
            raise KeyError(f"Unbekannter Provider: {provider_id}")
        return self._providers[provider_id]
