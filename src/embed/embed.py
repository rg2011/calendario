import argparse
import locale
import os
import sys
from datetime import date, datetime
from typing import List, Protocol
import requests


class OpenEmbed:
    """Implementación de EmbeddingProvider usando la API compatible con OpenAI (Ollama)."""

    VERSION = "1.0.0"

    def __init__(self) -> None:
        self._api_url = os.environ.get("EMBEDDING_API_URL", "http://localhost:11434/v1")
        self._api_key = os.environ.get("EMBEDDING_API_KEY", "")
        self._model_name = os.environ.get(
            "EMBEDDING_MODEL",
            "nomic-embed-text:latest"
        )
        # Ensure English locale for strftime
        locale.setlocale(locale.LC_TIME, "C")

    def embeddingURI(self) -> str:
        return f"{self._model_name}:{self.VERSION}"

    def embedFact(self, target_date: date, fact: str) -> List[float]:
        date_str = target_date.strftime("%A, %d %B %Y")
        text = f"Nota de la fecha {date_str}: {fact}"
        return self._get_embedding(text)

    def embedQuery(self, query: str) -> List[float]:
        return self._get_embedding(query)

    def _get_embedding(self, text: str) -> List[float]:
        payload = {
            "model": self._model_name,
            "input": text,
        }
        headers = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        response = requests.post(
            f"{self._api_url}/embeddings",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]


def _print_embedding(embedding: List[float]) -> None:
    """Print the embedding as a list of floats."""
    print(f"Dimension: {len(embedding)}")
    print(f"Values: {embedding[:10]}...")  # Show first 10 values


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Test OpenEmbed CLI for generating embeddings."
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # embedFact command
    fact_parser = subparsers.add_parser("fact", help="Generate embedding for a date and fact")
    fact_parser.add_argument("--date", type=str, default=None, help="Date in YYYY-MM-DD format (default: today)")
    fact_parser.add_argument("text", nargs="?", default="", help="The fact/note text")

    # embedQuery command
    query_parser = subparsers.add_parser("query", help="Generate embedding for a query string")
    query_parser.add_argument("text", help="The query text")

    # Common options
    parser.add_argument("--model", type=str, default=None, help="Override EMBEDDING_MODEL env var")
    parser.add_argument("--api-url", type=str, default=None, help="Override EMBEDDING_API_URL env var")
    parser.add_argument("--api-key", type=str, default=None, help="Override EMBEDDING_API_KEY env var")
    parser.add_argument("--uri", action="store_true", help="Print the embedding URI instead of generating embeddings")

    args = parser.parse_args()

    api_url = args.api_url or os.environ.get("EMBEDDING_API_URL", "http://localhost:11434/v1")
    api_key = args.api_key or os.environ.get("EMBEDDING_API_KEY", "")
    model_name = args.model or os.environ.get("EMBEDDING_MODEL", "nomic-embed-text:latest")

    # Override env vars for OpenEmbed
    os.environ["EMBEDDING_API_URL"] = api_url
    os.environ["EMBEDDING_API_KEY"] = api_key
    os.environ["EMBEDDING_MODEL"] = model_name

    provider = OpenEmbed()

    if args.uri:
        print(provider.embeddingURI())
        sys.exit(0)

    if args.command == "fact":
        if not args.text:
            print("Error: Please provide a fact text.", file=sys.stderr)
            sys.exit(1)
        
        if args.date:
            try:
                target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
            except ValueError:
                print(f"Error: Invalid date format '{args.date}'. Use YYYY-MM-DD.", file=sys.stderr)
                sys.exit(1)
        else:
            target_date = date.today()

        print(f"Date: {target_date}")
        print(f"Text: Nota de la fecha {target_date.strftime('%A, %d %B %Y')}: {args.text}")
        embedding = provider.embedFact(target_date, args.text)
        _print_embedding(embedding)

    elif args.command == "query":
        if not args.text:
            print("Error: Please provide a query text.", file=sys.stderr)
            sys.exit(1)

        print(f"Query: {args.text}")
        embedding = provider.embedQuery(args.text)
        _print_embedding(embedding)

    else:
        parser.print_help()
        sys.exit(1)
