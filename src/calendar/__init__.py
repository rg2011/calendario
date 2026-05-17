from .constants import DAYS_OF_WEEK_ABBR, MONTH_NAMES_ES
from .service import CalendarService, New

__all__ = [
    "CalendarService",
    "DAYS_OF_WEEK_ABBR",
    "MONTH_NAMES_ES",
    "New",
]

# API pública reexportada:
# - `New`: construye el servicio de calendario con sus dependencias de dominio
# - `CalendarService`: implementación concreta de navegación mensual y contexto
# - `MONTH_NAMES_ES` y `DAYS_OF_WEEK_ABBR`: constantes de presentación del calendario
