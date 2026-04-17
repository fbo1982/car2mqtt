from __future__ import annotations

import abc
from typing import Any, Dict

from ..models import ProviderSchema, VehicleConfig


class ProviderAdapter(abc.ABC):
    manufacturer: str

    def __init__(self, vehicle: VehicleConfig) -> None:
        self.vehicle = vehicle

    @classmethod
    @abc.abstractmethod
    def schema(cls) -> ProviderSchema:
        raise NotImplementedError

    @abc.abstractmethod
    async def validate_config(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def start(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def stop(self) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    async def health(self) -> Dict[str, Any]:
        raise NotImplementedError
