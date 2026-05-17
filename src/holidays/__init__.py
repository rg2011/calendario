from collections.abc import Iterable
from datetime import date
from logging import Logger
from typing import Protocol

from src.httpcache import CacheState

from .holidays import HolidayService


class HolidayProvider(Protocol):
    """Contrato tipado del subsistema de festivos."""

    def get_month_holidays(self, year: int, month: int) -> dict[str, dict[str, list[str]]]:
        """Devuelve los festivos de un mes, indexados por fecha ISO."""
        ...

    def get_holidays_for_dates(
        self,
        dates_to_check: Iterable[date],
    ) -> dict[str, dict[str, list[str]]]:
        """Devuelve los festivos visibles para un conjunto de fechas."""
        ...

    def ensure_refresh_worker(self) -> None:
        """Arranca el worker de refresco si todavía no está en ejecución."""
        ...


def New(logger: Logger, cache_state: CacheState) -> HolidayProvider:
    """Construye la implementación concreta del proveedor de festivos."""
    return HolidayService(logger=logger, cache_state=cache_state)


__all__ = [
    'HolidayProvider',
    'New',
]

# API pública reexportada:
# - `New`: construye el servicio de festivos con logger y cache HTTP
# - `HolidayProvider`: contrato mínimo que consumen calendario y arranque
