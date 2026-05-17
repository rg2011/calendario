from flask import Flask

from src.holidays import HolidayProvider
from src.httpcache import CacheState
from src.models import db

from .schema import ensure_absence_schema, ensure_custom_shift_schema


def initialize_runtime(
    app: Flask,
    holiday_provider: HolidayProvider,
    cache_state: CacheState,
) -> None:
    """Crea tablas, aplica migraciones inline y arranca workers en background."""
    db.create_all()
    ensure_custom_shift_schema(app.logger, cache_state)
    ensure_absence_schema(app.logger, cache_state)
    holiday_provider.ensure_refresh_worker()


def register_startup(
    app: Flask,
    holiday_provider: HolidayProvider,
    cache_state: CacheState,
) -> None:
    """Conecta la inicialización al ciclo de vida de Flask."""

    @app.before_request
    def initialize_on_request() -> None:
        initialize_runtime(app, holiday_provider, cache_state)
