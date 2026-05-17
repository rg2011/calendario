from collections.abc import Iterable
from datetime import date, datetime

from src.httpcache import CacheState
from src.models import Absence, db


class AbsenceService:
    """Consultas y operaciones CRUD sobre ausencias."""

    def __init__(self, people: list[str], cache_state: CacheState) -> None:
        self._people = set(people)
        self._cache_state = cache_state

    def list_absences(self) -> list[Absence]:
        """Devuelve todas las ausencias ordenadas para UI y API."""
        return Absence.query.order_by(Absence.start_date.desc(), Absence.person).all()

    def get_absences_for_dates(self, dates_to_check: Iterable[date]) -> dict[str, list[str]]:
        """Devuelve un mapa fecha ISO -> personas ausentes para las fechas indicadas."""
        dates = list(dates_to_check)
        if not dates:
            return {}

        min_date = min(dates)
        max_date = max(dates)
        absences = (
            Absence.query.filter(Absence.start_date <= max_date, Absence.end_date >= min_date)
            .order_by(Absence.start_date, Absence.person)
            .all()
        )

        absences_by_date = {target_date.isoformat(): [] for target_date in dates}
        for absence in absences:
            current = max(absence.start_date, min_date)
            last = min(absence.end_date, max_date)
            while current <= last:
                people = absences_by_date.setdefault(current.isoformat(), [])
                if absence.person not in people:
                    people.append(absence.person)
                current = current.fromordinal(current.toordinal() + 1)

        return absences_by_date

    def is_person_absent_on_date(
        self,
        person: str | None,
        shift_date: date,
        absent_people: list[str] | None = None,
    ) -> bool:
        """Indica si una persona está ausente en una fecha concreta."""
        if not person:
            return False

        if absent_people is not None:
            return person in absent_people

        return (
            Absence.query.filter_by(person=person)
            .filter(Absence.start_date <= shift_date, Absence.end_date >= shift_date)
            .first()
            is not None
        )

    def delete_absence(
        self, person: str | None, start_date_str: str | None
    ) -> tuple[dict[str, object], int]:
        """Borra una ausencia por clave compuesta, devolviendo payload HTTP y status."""
        if not person or not start_date_str:
            return {"success": False, "error": "Datos no válidos"}, 400

        start_date = datetime.fromisoformat(start_date_str).date()
        absence = Absence.query.filter_by(person=person, start_date=start_date).first()
        if not absence:
            return {"success": False, "error": "Ausencia no encontrada"}, 404

        db.session.delete(absence)
        db.session.commit()
        self._cache_state.touch_data()
        return {"success": True}, 200

    def save_absence(self, data: dict[str, object]) -> tuple[dict[str, object], int]:
        """Crea o actualiza una ausencia, incluyendo el caso de cambio de clave."""
        start_date_str = self._as_string(data.get("start_date"))
        end_date_str = self._as_string(data.get("end_date"))
        person = self._as_string(data.get("person"))
        original_person = self._as_string(data.get("original_person"))
        original_start_date_str = self._as_string(data.get("original_start_date"))

        if not start_date_str or not end_date_str or person not in self._people:
            return {"success": False, "error": "Datos no válidos"}, 400

        start_date = datetime.fromisoformat(start_date_str).date()
        end_date = datetime.fromisoformat(end_date_str).date()
        if end_date < start_date:
            return {
                "success": False,
                "error": "La fecha final no puede ser anterior a la inicial",
            }, 400

        original_start_date = (
            datetime.fromisoformat(original_start_date_str).date()
            if original_start_date_str
            else None
        )

        if original_person and original_start_date:
            original_absence = Absence.query.filter_by(
                person=original_person,
                start_date=original_start_date,
            ).first()
            if original_absence and (
                original_person != person or original_start_date != start_date
            ):
                db.session.delete(original_absence)
                db.session.flush()

        absence = Absence.query.filter_by(person=person, start_date=start_date).first()
        if not absence:
            absence = Absence(person=person, start_date=start_date)

        absence.end_date = end_date
        db.session.add(absence)
        db.session.commit()
        self._cache_state.touch_data()
        return {"success": True}, 200

    def _as_string(self, value: object) -> str | None:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return None


def New(people: list[str], cache_state: CacheState) -> AbsenceService:
    """Construye el servicio de ausencias."""
    return AbsenceService(people=people, cache_state=cache_state)
