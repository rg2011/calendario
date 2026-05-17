from datetime import date, datetime, timedelta
from typing import Any

from src.absences.service import AbsenceService
from src.httpcache import CacheState
from src.models import CustomShift, DayWeekRule, db


class ShiftService:
    """Lógica de negocio de reglas semanales, custom shifts y resúmenes diarios."""

    def __init__(
        self,
        people: list[str],
        absence_service: AbsenceService,
        cache_state: CacheState,
    ) -> None:
        self._people = set(people)
        self._absence_service = absence_service
        self._cache_state = cache_state

    def get_week_start(self, target_date: date) -> date:
        """Devuelve el lunes de la semana de una fecha."""
        return target_date - timedelta(days=target_date.weekday())

    def get_default_shift_for_day(self, shift_date: date) -> str | None:
        """Obtiene la persona asignada por la regla semanal del día."""
        day_of_week = shift_date.weekday()
        rule = DayWeekRule.query.filter_by(day_of_week=day_of_week).first()

        if not rule:
            return None

        if rule.algorithm == 'fijo':
            return rule.person_fijo

        if rule.algorithm == 'rotatorio':
            if not rule.rotation_order or not rule.rotation_start_date:
                return None

            people_list = [p.strip() for p in rule.rotation_order.split(',') if p.strip()]
            if len(people_list) != 3:
                return None

            start_week = self.get_week_start(rule.rotation_start_date)
            shift_week = self.get_week_start(shift_date)

            if shift_week < start_week:
                return None

            weeks_diff = (shift_week - start_week).days // 7
            person_index = weeks_diff % len(people_list)
            return people_list[person_index]

        return None

    def get_shift_for_day(
        self,
        shift_date: date,
        absent_people: list[str] | None = None,
    ) -> tuple[str | None, bool, str | None, str | None]:
        """Obtiene el turno efectivo de un día, aplicando ausencias y custom shift."""
        default_person = self.get_default_shift_for_day(shift_date)
        if self._absence_service.is_person_absent_on_date(default_person, shift_date, absent_people):
            default_person = None

        custom = CustomShift.query.filter_by(shift_date=shift_date).first()
        if custom:
            effective_person = custom.person if custom.person else default_person
            return effective_person, True, custom.note, custom.person

        return default_person, False, None, None

    def get_shift_summary_for_date(self, shift_date: date) -> dict[str, Any]:
        """Resume el estado de turno para una fecha concreta."""
        absent_people = self._absence_service.get_absences_for_dates([shift_date]).get(
            shift_date.isoformat(),
            [],
        )
        default_person = self.get_default_shift_for_day(shift_date)
        if self._absence_service.is_person_absent_on_date(default_person, shift_date, absent_people):
            default_person = None
        person, is_custom, note, custom_person = self.get_shift_for_day(shift_date, absent_people)
        return {
            'date': shift_date,
            'date_iso': shift_date.isoformat(),
            'person': person,
            'default_person': default_person,
            'custom_person': custom_person,
            'is_custom': is_custom,
            'note': note,
            'absent_people': absent_people,
        }

    def list_rules(self) -> list[DayWeekRule]:
        """Devuelve todas las reglas semanales ordenadas por día."""
        return DayWeekRule.query.order_by(DayWeekRule.day_of_week).all()

    def rules_by_day(self) -> dict[int, DayWeekRule]:
        """Devuelve las reglas indexadas por día de la semana."""
        return {rule.day_of_week: rule for rule in DayWeekRule.query.all()}

    def save_rule(self, data: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Crea o actualiza una regla semanal."""
        day_of_week = data.get('day_of_week')
        algorithm = data.get('algorithm')

        rule = DayWeekRule.query.filter_by(day_of_week=day_of_week).first()
        if not rule:
            rule = DayWeekRule()
            rule.day_of_week = day_of_week

        rule.algorithm = algorithm

        if algorithm == 'fijo':
            rule.person_fijo = self._as_string(data.get('person_fijo'))
            rule.rotation_order = None
            rule.rotation_start_date = None
        elif algorithm == 'rotatorio':
            rule.person_fijo = None
            rule.rotation_order = self._as_string(data.get('rotation_order'))
            start_date_str = self._as_string(data.get('rotation_start_date'))
            rule.rotation_start_date = (
                datetime.fromisoformat(start_date_str).date() if start_date_str else None
            )

        db.session.add(rule)
        db.session.commit()
        self._cache_state.touch_data()
        return {'success': True, 'id': rule.id}, 200

    def set_custom_shift(self, data: dict[str, Any]) -> tuple[dict[str, Any], int]:
        """Crea, actualiza o elimina un custom shift para una fecha concreta."""
        shift_date_str = self._as_string(data.get('shift_date'))
        raw_person = self._as_string(data.get('person')) or ''
        person = raw_person or None
        note = self._as_string(data.get('note'))

        if not shift_date_str:
            return {'success': False, 'error': 'Invalid data'}, 400

        shift_date = datetime.fromisoformat(shift_date_str).date()
        should_delete = raw_person == 'clear'
        if should_delete:
            person = None

        if person and person not in self._people:
            return {'success': False, 'error': 'Persona no válida'}, 400
        if person and self._absence_service.is_person_absent_on_date(person, shift_date):
            return {'success': False, 'error': 'La persona está ausente en esa fecha'}, 400

        custom = CustomShift.query.filter_by(shift_date=shift_date).first()

        should_delete = should_delete or (not person and not note)
        if should_delete:
            if custom:
                db.session.delete(custom)
                db.session.commit()
                self._cache_state.touch_data()
        else:
            if not custom:
                custom = CustomShift()
                custom.shift_date = shift_date
            custom.person = person
            custom.note = note
            db.session.add(custom)
            db.session.commit()
            self._cache_state.touch_data()

        return {'success': True}, 200

    def _as_string(self, value: object) -> str | None:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return None


def New(
    people: list[str],
    absence_service: AbsenceService,
    cache_state: CacheState,
) -> ShiftService:
    """Construye el servicio de turnos."""
    return ShiftService(
        people=people,
        absence_service=absence_service,
        cache_state=cache_state,
    )
