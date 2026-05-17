import calendar
import json
import time
from collections.abc import Iterable
from datetime import date, datetime
from logging import Logger
from threading import Lock, Thread
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from src.httpcache import CacheState

HOLIDAY_API_URL = 'https://datos.juntadeandalucia.es/api/v0/work-calendar/get/search_calendar'
HOLIDAY_API_PROVINCE = 'SEVILLA'
HOLIDAY_API_MUNICIPALITY = 'SEVILLA'
HOLIDAY_CACHE_VERSION = 'junta-v2'
HOLIDAY_API_TIMEOUT_SECONDS = 8
HOLIDAY_REFRESH_INITIAL_DELAY_SECONDS = 2
HOLIDAY_REFRESH_MAX_BACKOFF_SECONDS = 30
HOLIDAY_REFRESH_SUCCESS_INTERVAL_SECONDS = 6 * 60 * 60

HolidayEntry = dict[str, list[str]]
HolidayMap = dict[str, HolidayEntry]


class HolidayService:
    """Gestiona la consulta, caché y refresco en background de festivos."""

    def __init__(self, logger: Logger, cache_state: CacheState) -> None:
        self._logger = logger
        self._cache_state = cache_state
        self._holiday_cache: dict[tuple[str, int, int | str], HolidayMap] = {}
        self._holiday_cache_lock = Lock()
        self._holiday_refresh_thread: Thread | None = None
        self._holiday_refresh_thread_lock = Lock()

    def extract_holiday_rows(self, payload: Any) -> list[dict[str, Any]]:
        """Normaliza la respuesta de la API a una lista de registros."""
        if isinstance(payload, list):
            return payload

        if isinstance(payload, dict):
            for key in ('results', 'items', 'records', 'data'):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
            for value in payload.values():
                if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                    return value

        return []

    def parse_holiday_date(self, holiday: dict[str, Any]) -> date | None:
        """Extrae la fecha del registro con cierta tolerancia a variantes de clave."""
        raw_date = holiday.get('dateformat') or holiday.get('startDate') or holiday.get('date')
        if not raw_date:
            return None

        if isinstance(raw_date, int):
            raw_date = str(raw_date)

        if not isinstance(raw_date, str):
            return None

        raw_date = raw_date.strip()
        for candidate in (raw_date[:10], raw_date):
            try:
                return date.fromisoformat(candidate)
            except ValueError:
                continue

        for fmt in ('%Y%m%d', '%d/%m/%Y', '%d-%m-%Y'):
            try:
                return datetime.strptime(raw_date, fmt).date()
            except ValueError:
                continue

        return None

    def extract_holiday_name(self, holiday: dict[str, Any]) -> str:
        """Obtiene el nombre visible del festivo desde la API de la Junta."""
        for key in ('description', 'event', 'name', 'title'):
            value = holiday.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return 'Festivo'

    def fetch_holidays_from_api(self, year: int) -> HolidayMap:
        """Consulta la API oficial y devuelve un mapa de fecha ISO a festivo."""
        params = {
            'province': HOLIDAY_API_PROVINCE,
            'municipality': HOLIDAY_API_MUNICIPALITY,
            'year': str(year),
        }
        url = f'{HOLIDAY_API_URL}?{urlencode(params)}'
        self._logger.info('Consultando API de festivos: %s', url)

        try:
            with urlopen(url, timeout=HOLIDAY_API_TIMEOUT_SECONDS) as response:
                if response.status != 200:
                    self._logger.warning(
                        'Respuesta no satisfactoria al consultar festivos: %s',
                        response.status,
                    )
                    return {}
                payload = json.loads(response.read().decode('utf-8'))
        except Exception as exc:
            self._logger.warning(
                'Error consultando la API de festivos para %s: %s: %s',
                year,
                type(exc).__name__,
                exc,
            )
            return {}

        rows = self.extract_holiday_rows(payload)
        self._logger.info('API de festivos %s: %s registros brutos recibidos', year, len(rows))

        holidays_by_date: HolidayMap = {}
        for holiday in rows:
            holiday_date = self.parse_holiday_date(holiday)
            holiday_name = self.extract_holiday_name(holiday)
            holiday_type = holiday.get('type') or 'LABORAL'
            if not holiday_date or not holiday_name:
                continue

            holiday_entry = holidays_by_date.setdefault(
                holiday_date.isoformat(),
                {'names': [], 'scopes': []},
            )
            if holiday_name not in holiday_entry['names']:
                holiday_entry['names'].append(holiday_name)
            if holiday_type not in holiday_entry['scopes']:
                holiday_entry['scopes'].append(holiday_type)

        self._logger.info(
            'Festivos anualizados %s: %s fechas unicas (%s)',
            year,
            len(holidays_by_date),
            ', '.join(
                f'{holiday_date}={holiday_info["names"]}'
                for holiday_date, holiday_info in sorted(holidays_by_date.items())
            ) or 'sin resultados',
        )
        return holidays_by_date

    def build_month_holiday_cache(self, year: int, year_holidays: HolidayMap) -> dict[tuple[str, int, int], HolidayMap]:
        """Construye la caché mensual completa a partir de los festivos anualizados."""
        monthly_cache = {}

        for month in range(1, 13):
            month_start, month_end = self._month_date_range(year, month)
            monthly_cache[(HOLIDAY_CACHE_VERSION, year, month)] = {
                holiday_date: holiday_info
                for holiday_date, holiday_info in year_holidays.items()
                if month_start <= date.fromisoformat(holiday_date) <= month_end
            }

        return monthly_cache

    def get_year_cache_key(self, year: int) -> tuple[str, int, str]:
        return (HOLIDAY_CACHE_VERSION, year, 'full_year')

    def get_month_cache_key(self, year: int, month: int) -> tuple[str, int, int]:
        return (HOLIDAY_CACHE_VERSION, year, month)

    def get_cached_year_holidays(self, year: int) -> HolidayMap | None:
        with self._holiday_cache_lock:
            return self._holiday_cache.get(self.get_year_cache_key(year))

    def update_holiday_cache(self, year: int, year_holidays: HolidayMap) -> bool:
        with self._holiday_cache_lock:
            year_cache_key = self.get_year_cache_key(year)
            current_year_holidays = self._holiday_cache.get(year_cache_key)
            if current_year_holidays == year_holidays:
                return False

            self._holiday_cache[year_cache_key] = year_holidays
            self._holiday_cache.update(self.build_month_holiday_cache(year, year_holidays))

        self._cache_state.touch_holidays()
        return True

    def refresh_holiday_cache_for_year(self, year: int) -> bool:
        """Intenta refrescar la caché anual de festivos y devuelve True si tuvo éxito."""
        if year != date.today().year:
            self._logger.info(
                'Se omite la recarga de festivos para %s porque no es el año en curso',
                year,
            )
            return False

        year_holidays = self.fetch_holidays_from_api(year)
        if not year_holidays:
            self._logger.warning('No se pudieron obtener festivos para %s', year)
            return False

        updated = self.update_holiday_cache(year, year_holidays)
        if updated:
            self._logger.info(
                'Caché anual de festivos actualizada para %s: %s fechas',
                year,
                len(year_holidays),
            )
        else:
            self._logger.info('La caché anual de festivos para %s ya estaba al día', year)
        return True

    def holiday_refresh_worker(self) -> None:
        """Mantiene la caché de festivos actualizada sin bloquear peticiones."""
        retry_delay = HOLIDAY_REFRESH_INITIAL_DELAY_SECONDS

        while True:
            current_year = date.today().year
            has_cache = self.get_cached_year_holidays(current_year) is not None

            success = self.refresh_holiday_cache_for_year(current_year)
            if success:
                retry_delay = HOLIDAY_REFRESH_INITIAL_DELAY_SECONDS
                time.sleep(HOLIDAY_REFRESH_SUCCESS_INTERVAL_SECONDS)
                continue

            if has_cache:
                time.sleep(HOLIDAY_REFRESH_SUCCESS_INTERVAL_SECONDS)
                continue

            self._logger.info(
                'Reintentando recarga de festivos para %s en %s segundos',
                current_year,
                retry_delay,
            )
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, HOLIDAY_REFRESH_MAX_BACKOFF_SECONDS)

    def ensure_refresh_worker(self) -> None:
        """Arranca el worker de festivos si todavía no está vivo."""
        with self._holiday_refresh_thread_lock:
            if self._holiday_refresh_thread and self._holiday_refresh_thread.is_alive():
                return

            self._holiday_refresh_thread = Thread(
                target=self.holiday_refresh_worker,
                name='holiday-refresh',
                daemon=True,
            )
            self._holiday_refresh_thread.start()
            self._logger.info('Worker de recarga de festivos iniciado')

    def get_month_holidays(self, year: int, month: int) -> HolidayMap:
        """Devuelve los festivos de un mes usando la caché en memoria."""
        if year != date.today().year:
            return {}

        cache_key = self.get_month_cache_key(year, month)
        with self._holiday_cache_lock:
            month_holidays = self._holiday_cache.get(cache_key)

        if month_holidays is None:
            self._logger.info(
                'Festivos %s-%02d no disponibles en cache; devolviendo calendario sin festivos',
                year,
                month,
            )
            return {}

        self._logger.info(
            'Festivos %s-%02d obtenidos de cache mensual: %s fechas',
            year,
            month,
            len(month_holidays),
        )
        return month_holidays

    def get_holidays_for_dates(self, dates_to_check: Iterable[date]) -> HolidayMap:
        """Obtiene festivos para todas las fechas visibles del calendario."""
        holidays: HolidayMap = {}
        visible_months = sorted({(day.year, day.month) for day in dates_to_check})

        for year, month in visible_months:
            holidays.update(self.get_month_holidays(year, month))

        return holidays

    def _month_date_range(self, year: int, month: int) -> tuple[date, date]:
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last_day)
