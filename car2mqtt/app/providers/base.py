from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict
from app.core.models import ProviderDescriptor


class BaseProvider(ABC):
    @abstractmethod
    def descriptor(self) -> ProviderDescriptor:
        raise NotImplementedError

    @abstractmethod
    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def map_example(self) -> Dict[str, Any]:
        return {}
