#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SKILL_ID = "amzn1.ask.skill.69beb30b-39d1-40bd-8836-d36afcea1f61"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def load_secret_path() -> str:
    load_dotenv(ROOT_DIR / ".env")
    secret_path = (os.environ.get("CALENDARIO_SECRET_PATH") or "").strip().strip("/")
    if not secret_path:
        raise RuntimeError("Falta CALENDARIO_SECRET_PATH en .env o en el entorno")
    if "/" in secret_path:
        raise RuntimeError('CALENDARIO_SECRET_PATH debe ser un unico segmento de ruta, sin "/"')
    return secret_path


def build_payload(args: argparse.Namespace) -> dict:
    base = {
        "context": {
            "System": {
                "application": {
                    "applicationId": args.skill_id,
                }
            }
        }
    }

    if args.request_type == "LaunchRequest":
        base["request"] = {"type": "LaunchRequest"}
        return base

    base["request"] = {
        "type": "IntentRequest",
        "intent": {
            "name": args.intent,
            "slots": {
                "target_date": {
                    "name": "target_date",
                    "value": args.date_value,
                }
            },
        },
    }
    return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prueba local del webhook Alexa")
    parser.add_argument("--host", default="http://127.0.0.1:5000")
    parser.add_argument("--skill-id", default=os.environ.get("ALEXA_SKILL_ID") or DEFAULT_SKILL_ID)
    parser.add_argument(
        "--request-type",
        choices=["LaunchRequest", "IntentRequest"],
        default="IntentRequest",
    )
    parser.add_argument("--intent", default="QueryShiftIntent")
    parser.add_argument("--date-value", default="PRESENT_REF")
    args = parser.parse_args(argv)

    secret_path = load_secret_path()
    payload = build_payload(args)

    try:
        from app import app
    except Exception as exc:
        print(f"ERROR: no se pudo importar app.py: {exc}", file=sys.stderr)
        return 2

    client = app.test_client()
    response = client.post(f"/{secret_path}/alexa", json=payload)
    print(json.dumps(
        {
            "status_code": response.status_code,
            "path": f"/{secret_path}/alexa",
            "request": payload,
            "response": response.get_json(),
        },
        ensure_ascii=True,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
