from src.models import DayWeekRule


def serialize_rule(rule: DayWeekRule) -> dict[str, str | int | None]:
    """Serializa una regla para respuestas JSON o plantillas."""
    return {
        'id': rule.id,
        'day_of_week': rule.day_of_week,
        'algorithm': rule.algorithm,
        'person_fijo': rule.person_fijo,
        'rotation_order': rule.rotation_order,
        'rotation_start_date': rule.rotation_start_date.isoformat() if rule.rotation_start_date else None,
    }
