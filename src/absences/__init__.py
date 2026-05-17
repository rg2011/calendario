from .serializers import serialize_absence
from .service import AbsenceService, New

__all__ = [
    'AbsenceService',
    'New',
    'serialize_absence',
]

# API pública reexportada:
# - `New`: construye el servicio de ausencias sobre SQLAlchemy y cache HTTP
# - `AbsenceService`: implementación concreta con consultas y operaciones CRUD
# - `serialize_absence`: adaptación simple del modelo a JSON/contexto de plantilla
