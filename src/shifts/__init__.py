from .serializers import serialize_rule
from .service import New, ShiftService

__all__ = [
    'New',
    'ShiftService',
    'serialize_rule',
]

# API pública reexportada:
# - `New`: construye el servicio de turnos con personas válidas, ausencias y cache HTTP
# - `ShiftService`: implementación concreta de reglas, custom shifts y resúmenes diarios
# - `serialize_rule`: adaptación simple del modelo a JSON/contexto de plantilla
