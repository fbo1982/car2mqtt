from __future__ import annotations

from typing import Dict, Type

from ..models import Manufacturer, ProviderSchema, VehicleConfig
from .base import ProviderAdapter
from .bmw import BMWProvider
from .gwm import GWMProvider


PROVIDERS: Dict[str, Type[ProviderAdapter]] = {
    BMWProvider.manufacturer: BMWProvider,
    GWMProvider.manufacturer: GWMProvider,
}


def get_provider(vehicle: VehicleConfig) -> ProviderAdapter:
    provider_cls = PROVIDERS[vehicle.manufacturer.value]
    return provider_cls(vehicle)


def provider_schemas() -> list[ProviderSchema]:
    return [provider.schema() for provider in PROVIDERS.values()]
