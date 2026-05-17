from datetime import date
from typing import List, Protocol
from .embed import OpenEmbed


class EmbeddingProvider(Protocol):
    """Contrato tipado para generar embeddings del dominio."""

    def embeddingURI(self) -> str:
        """Devuelve la URI estable del modelo/proveedor de embeddings."""
        return "embedding://my_embedding_model/v1"

    def embedFact(self, target_date: date, fact: str) -> List[float]:
        """Genera el array de floats asociado a una fecha y una nota."""
        return []

    def embedQuery(self, query: str) -> List[float]:
        """Genera el array de floats asociado a una consulta."""
        return []


def New() -> EmbeddingProvider:
    """Constructor para obtener una instancia concreta de EmbeddingProvider."""
    return OpenEmbed()
