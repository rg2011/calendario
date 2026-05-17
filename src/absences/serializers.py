from src.models import Absence


def serialize_absence(absence: Absence) -> dict[str, str]:
    """Serializa una ausencia para respuestas JSON o plantillas."""
    return {
        'start_date': absence.start_date.isoformat(),
        'end_date': absence.end_date.isoformat(),
        'person': absence.person,
    }
