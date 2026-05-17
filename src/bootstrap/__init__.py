from .schema import ensure_absence_schema, ensure_custom_shift_schema
from .startup import initialize_runtime, register_startup

__all__ = [
    "ensure_absence_schema",
    "ensure_custom_shift_schema",
    "initialize_runtime",
    "register_startup",
]

# API pública reexportada:
# - `ensure_custom_shift_schema` y `ensure_absence_schema`: migraciones inline del esquema actual
# - `initialize_runtime`: crea tablas, aplica migraciones y arranca workers
# - `register_startup`: conecta la inicialización al ciclo de vida Flask
