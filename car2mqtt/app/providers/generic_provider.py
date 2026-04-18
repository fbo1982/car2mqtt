from __future__ import annotations

from typing import Any, Dict, List
from app.core.models import ProviderDescriptor
from app.providers.base import BaseProvider


class GenericConfigProvider(BaseProvider):
    def __init__(
        self,
        provider_id: str,
        name: str,
        badge: str,
        notes: str,
        fields: List[Dict[str, Any]],
        setup_steps: List[str] | None = None,
        category: str = "API",
        auth_mode: str = "config_wizard",
    ) -> None:
        self._descriptor = ProviderDescriptor(
            id=provider_id,
            name=name,
            category=category,
            auth_mode=auth_mode,
            badge=badge,
            notes=notes,
            fields=fields,
            setup_steps=setup_steps or [],
        )

    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def validate_config(self, provider_config: Dict[str, Any]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for field in self._descriptor.fields:
            name = field['name']
            field_type = field.get('type', 'text')
            required = bool(field.get('required', False))
            default = field.get('default', '')
            value = provider_config.get(name, default)
            if field_type == 'checkbox':
                result[name] = bool(value)
                continue
            if field_type == 'number':
                raw = str(value).strip()
                if not raw:
                    if required:
                        raise ValueError(f"{field['label']} ist erforderlich.")
                    result[name] = ''
                    continue
                try:
                    result[name] = int(raw) if raw.isdigit() else float(raw)
                except Exception as exc:
                    raise ValueError(f"{field['label']} muss numerisch sein.") from exc
                continue
            text = str(value).strip()
            if required and not text:
                raise ValueError(f"{field['label']} ist erforderlich.")
            result[name] = text
        return result
