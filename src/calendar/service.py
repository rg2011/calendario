import calendar
from collections.abc import Callable
from datetime import date, datetime, timedelta
from logging import Logger
from typing import Any

from src.absences.service import AbsenceService
from src.holidays import HolidayProvider
from src.shifts.service import ShiftService

from .constants import DAYS_OF_WEEK, DAYS_OF_WEEK_ABBR, MONTH_NAMES_ES


class CalendarService:
    """Construye el modelo mensual y el contexto de render del calendario."""

    def __init__(
        self,
        people: list[str],
        logger: Logger,
        absence_service: AbsenceService,
        holiday_provider: HolidayProvider,
        shift_service: ShiftService,
    ) -> None:
        self._people = sorted(people)
        self._logger = logger
        self._absence_service = absence_service
        self._holiday_provider = holiday_provider
        self._shift_service = shift_service

    def get_previous_month(self, year: int, month: int) -> tuple[int, int]:
        """Devuelve el mes anterior como tupla `(year, month)`."""
        if month == 1:
            return year - 1, 12
        return year, month - 1

    def get_next_month(self, year: int, month: int) -> tuple[int, int]:
        """Devuelve el mes siguiente como tupla `(year, month)`."""
        if month == 12:
            return year + 1, 1
        return year, month + 1

    def get_month_days_full(self, year: int, month: int) -> list[dict[str, Any]]:
        """Retorna los días visibles de la cuadrícula mensual."""
        days_list = []

        first_day_weekday = datetime(year, month, 1).weekday()
        if first_day_weekday > 0:
            prev_year, prev_month = self.get_previous_month(year, month)
            prev_days_in_month = calendar.monthrange(prev_year, prev_month)[1]
            for day in range(prev_days_in_month - first_day_weekday + 1, prev_days_in_month + 1):
                days_list.append(
                    {
                        "date": date(prev_year, prev_month, day),
                        "day_num": day,
                        "month_type": "prev",
                    }
                )

        for day in range(1, calendar.monthrange(year, month)[1] + 1):
            days_list.append(
                {
                    "date": date(year, month, day),
                    "day_num": day,
                    "month_type": "current",
                }
            )

        total_days_shown = len(days_list)
        if total_days_shown % 7 != 0:
            days_to_add = 7 - (total_days_shown % 7)
            next_year, next_month = self.get_next_month(year, month)
            for day in range(1, days_to_add + 1):
                days_list.append(
                    {
                        "date": date(next_year, next_month, day),
                        "day_num": day,
                        "month_type": "next",
                    }
                )

        return days_list

    def build_context(
        self,
        year: int,
        month: int,
        calendar_url_builder: Callable[[int, int], str],
        include_notes: bool = True,
    ) -> dict[str, Any]:
        """Construye el contexto completo de render del calendario mensual."""
        if month < 1 or month > 12:
            today = date.today()
            month = today.month
            year = today.year

        today = date.today()
        prev_year, prev_month = self.get_previous_month(year, month)
        next_year, next_month = self.get_next_month(year, month)

        days = self.get_month_days_full(year, month)
        visible_holidays = self._holiday_provider.get_holidays_for_dates(
            day["date"] for day in days
        )
        absences_by_date = self._absence_service.get_absences_for_dates(day["date"] for day in days)
        self._logger.info(
            "Render calendario %s-%02d con %s festivos detectados en dias visibles",
            year,
            month,
            len(visible_holidays),
        )

        for day in days:
            absent_people = absences_by_date.get(day["date"].isoformat(), [])
            default_person = self._shift_service.get_default_shift_for_day(day["date"])
            if self._absence_service.is_person_absent_on_date(
                default_person, day["date"], absent_people
            ):
                default_person = None
            person, is_custom, note, custom_person, tags = self._shift_service.get_shift_for_day(
                day["date"],
                absent_people,
            )
            holiday_info = visible_holidays.get(day["date"].isoformat())
            day["person"] = person
            day["default_person"] = default_person
            day["custom_person"] = custom_person
            day["is_custom"] = is_custom
            day["note"] = note if include_notes else None
            day["tags"] = tags
            day["absent_people"] = absent_people
            day["is_today"] = day["date"] == today
            day["holiday_name"] = " · ".join(holiday_info["names"]) if holiday_info else None
            day["is_holiday"] = bool(holiday_info)

        weeks = [days[index : index + 7] for index in range(0, len(days), 7)]
        month_options = [
            {"value": month_number, "label": MONTH_NAMES_ES[month_number]}
            for month_number in range(1, 13)
        ]
        current_year = today.year
        year_options = sorted({current_year - 1, current_year, current_year + 1, year})

        return {
            "year": year,
            "month": month,
            "month_name": MONTH_NAMES_ES[month],
            "month_options": month_options,
            "year_options": year_options,
            "holiday_reference_year": current_year,
            "weeks": weeks,
            "days_of_week": DAYS_OF_WEEK_ABBR,
            "prev_url": calendar_url_builder(prev_year, prev_month),
            "next_url": calendar_url_builder(next_year, next_month),
            "people": self._people,
        }


    def build_week_context(
        self,
        start: date,
        include_notes: bool = True,
    ) -> dict[str, Any]:
        """Construye el contexto completo de render del calendario semanal."""
        days: list[dict[str, Any]] = [{"date": start}]
        days.extend({"date": start + timedelta(days=d)} for d in range(1, 9))
        absences_by_date = self._absence_service.get_absences_for_dates(day["date"] for day in days)
        self._logger.info("Render semana %s", start.isoformat())

        for day in days:
            absent_people = absences_by_date.get(day["date"].isoformat(), [])
            default_person = self._shift_service.get_default_shift_for_day(day["date"])
            if self._absence_service.is_person_absent_on_date(
                default_person, day["date"], absent_people
            ):
                default_person = None
            person, is_custom, note, custom_person, tags = self._shift_service.get_shift_for_day(
                day["date"],
                absent_people,
            )
            day["label"] = "%d de %s" % (
                day["date"].day,
                MONTH_NAMES_ES[day["date"].month],
            )
            day["weekday"] = DAYS_OF_WEEK[day["date"].weekday()]
            day["person"] = person
            day["default_person"] = default_person
            day["custom_person"] = custom_person
            day["is_custom"] = is_custom
            day["note"] = note if include_notes else None
            day["tags"] = tags
            day["absent_people"] = absent_people
            day["is_today"] = day["date"] == start

        return {
            "start": start,
            "days": days,
            "people": self._people,
        }


def New(
    people: list[str],
    logger: Logger,
    absence_service: AbsenceService,
    holiday_provider: HolidayProvider,
    shift_service: ShiftService,
) -> CalendarService:
    """Construye el servicio de calendario."""
    return CalendarService(
        people=people,
        logger=logger,
        absence_service=absence_service,
        holiday_provider=holiday_provider,
        shift_service=shift_service,
    )
