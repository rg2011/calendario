from collections.abc import Callable
from typing import Any, Protocol

from .cache import (
    HttpCacheState,
    absences_cache_key,
    calendar_cache_key,
    current_month_cache_key,
    settings_cache_key,
)


class CacheState(Protocol):
    """Contrato tipado para la caché HTTP condicional de la aplicación."""

    def touch(self, *names: str) -> None:
        """Avanza la versión de uno o varios recursos lógicos."""
        ...

    def touch_data(self) -> None:
        """Marca como actualizados los datos de negocio."""
        ...

    def touch_holidays(self) -> None:
        """Marca como actualizados los datos de festivos."""
        ...

    def cached_view(
        self,
        resource_builder: Callable[..., str],
        version_names: tuple[str, ...],
        cache_control: str = 'private, no-cache',
        include_current_day: bool = False,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decora una vista Flask con soporte ETag y Last-Modified."""
        ...


def New() -> CacheState:
    """Construye la implementación concreta de `CacheState`."""
    return HttpCacheState()


__all__ = [
    'CacheState',
    'New',
    'absences_cache_key',
    'calendar_cache_key',
    'current_month_cache_key',
    'settings_cache_key',
]

# API pública reexportada:
# - `New`: constructor del estado de caché HTTP en memoria
# - `CacheState`: contrato mínimo que consumen las rutas
# - `calendar_cache_key` y `current_month_cache_key`: claves para vistas de calendario
# - `settings_cache_key` y `absences_cache_key`: claves para otras vistas cacheadas
