#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT_DIR / "alexa" / "config.json"
LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
SMAPI_BASE_URL = "https://api.amazonalexa.com"


class AlexaConfigError(RuntimeError):
    pass


@dataclass
class AlexaEnv:
    lwa_client_id: str
    lwa_client_secret: str
    lwa_refresh_token: str
    skill_id: str | None
    skill_stage: str
    invocation_name: str
    endpoint_base_url: str
    endpoint_path: str | None
    vendor_id: str | None

    @property
    def endpoint_url(self) -> str | None:
        if self.endpoint_path:
            return f"{self.endpoint_base_url.rstrip('/')}/{self.endpoint_path.lstrip('/')}"
        return None


def load_environment() -> AlexaEnv:
    load_dotenv(ROOT_DIR / ".env")

    def require(name: str) -> str:
        value = (os.environ.get(name) or "").strip()
        if not value:
            raise AlexaConfigError(f"Falta la variable requerida {name}")
        return value

    endpoint_url = (os.environ.get("ALEXA_ENDPOINT_URL") or "").strip()
    endpoint_base_url = (os.environ.get("ALEXA_ENDPOINT_BASE_URL") or "").strip()
    endpoint_path = (os.environ.get("ALEXA_ENDPOINT_PATH") or "").strip() or None
    if endpoint_url and not endpoint_base_url:
        parsed = parse.urlsplit(endpoint_url)
        if not parsed.scheme or not parsed.netloc:
            raise AlexaConfigError("ALEXA_ENDPOINT_URL no es una URL valida")
        endpoint_base_url = f"{parsed.scheme}://{parsed.netloc}"
        endpoint_path = parsed.path.lstrip("/") or endpoint_path
    if not endpoint_base_url:
        raise AlexaConfigError(
            "Falta ALEXA_ENDPOINT_BASE_URL o, alternativamente, ALEXA_ENDPOINT_URL"
        )

    return AlexaEnv(
        lwa_client_id=require("ALEXA_LWA_CLIENT_ID"),
        lwa_client_secret=require("ALEXA_LWA_CLIENT_SECRET"),
        lwa_refresh_token=require("ALEXA_LWA_REFRESH_TOKEN"),
        skill_id=(os.environ.get("ALEXA_SKILL_ID") or "").strip() or None,
        skill_stage=(os.environ.get("ALEXA_SKILL_STAGE") or "development").strip(),
        invocation_name=(os.environ.get("ALEXA_INVOCATION_NAME") or "calendario").strip(),
        endpoint_base_url=endpoint_base_url,
        endpoint_path=endpoint_path,
        vendor_id=(os.environ.get("ALEXA_VENDOR_ID") or "").strip() or None,
    )


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AlexaConfigError(f"No existe el fichero {path}") from exc
    except json.JSONDecodeError as exc:
        raise AlexaConfigError(f"JSON invalido en {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


class LwaClient:
    def __init__(self, env: AlexaEnv):
        self.env = env

    def get_access_token(self) -> dict[str, Any]:
        body = parse.urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": self.env.lwa_refresh_token,
                "client_id": self.env.lwa_client_id,
                "client_secret": self.env.lwa_client_secret,
            }
        ).encode("utf-8")
        req = request.Request(
            LWA_TOKEN_URL,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            method="POST",
        )
        return perform_request(req)


class SmapiClient:
    def __init__(self, access_token: str):
        self.access_token = access_token

    def _request(
        self,
        method: str,
        path: str,
        payload: Any | None = None,
        query: dict[str, str] | None = None,
        content_type: str = "application/json",
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        url = SMAPI_BASE_URL + path
        if query:
            url = f"{url}?{parse.urlencode(query)}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        data = None
        if payload is not None:
            headers["Content-Type"] = content_type
            if content_type == "application/json":
                data = json.dumps(payload).encode("utf-8")
            else:
                data = payload
        req = request.Request(url, data=data, headers=headers, method=method)
        return perform_request(req)

    def list_skills_for_vendor(self) -> Any:
        return self._request("GET", "/v1/skills")

    def get_skill_status(self, skill_id: str, stage: str) -> Any:
        return self._request("GET", f"/v1/skills/{skill_id}/status", query={"stage": stage})

    def get_interaction_model(self, skill_id: str, stage: str, locale: str) -> Any:
        return self._request(
            "GET",
            f"/v1/skills/{skill_id}/stages/{stage}/interactionModel/locales/{locale}",
        )

    def start_simulation(self, skill_id: str, stage: str, utterance: str, locale: str) -> Any:
        return self._request(
            "POST",
            f"/v2/skills/{skill_id}/stages/{stage}/simulations",
            payload={
                "session": {"mode": "FORCE_NEW_SESSION"},
                "input": {"content": utterance},
                "device": {"locale": locale},
            },
        )

    def get_simulation(self, skill_id: str, stage: str, simulation_id: str) -> Any:
        return self._request(
            "GET",
            f"/v2/skills/{skill_id}/stages/{stage}/simulations/{simulation_id}",
        )

    def get_skill_manifest(self, skill_id: str, stage: str) -> Any:
        return self._request("GET", f"/v1/skills/{skill_id}/manifest", query={"stage": stage})

    def update_skill_manifest(self, skill_id: str, stage: str, manifest: Any) -> Any:
        status = self.get_skill_status(skill_id, stage)
        etag = (((status or {}).get("manifest") or {}).get("eTag") or "").strip()
        if not etag:
            raise AlexaConfigError("No se pudo obtener el eTag actual del manifest")
        return self._request(
            "PUT",
            f"/v1/skills/{skill_id}/stages/{stage}/manifest",
            payload=manifest,
            extra_headers={"If-Match": etag},
        )

    def update_interaction_model(
        self,
        skill_id: str,
        stage: str,
        locale: str,
        model: Any,
        description: str,
    ) -> Any:
        return self._request(
            "PUT",
            f"/v1/skills/{skill_id}/stages/{stage}/interactionModel/locales/{locale}",
            payload={
                "description": description,
                "interactionModel": model["interactionModel"],
            },
        )


def perform_request(req: request.Request) -> Any:
    try:
        with request.urlopen(req, timeout=30) as response:
            raw = response.read().decode("utf-8")
            if not raw:
                return {}
            return json.loads(raw)
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise AlexaConfigError(
            f"HTTP {exc.code} al llamar a {req.full_url}\n{body}"
        ) from exc
    except error.URLError as exc:
        raise AlexaConfigError(f"Error de red al llamar a {req.full_url}: {exc}") from exc


def load_repo_config(path: Path) -> dict[str, Any]:
    return read_json(path)


def render_manifest(payload: dict[str, Any], env: AlexaEnv) -> dict[str, Any]:
    manifest = json.loads(json.dumps(payload))
    locales = manifest.setdefault("manifest", {}).setdefault("publishingInformation", {}).setdefault("locales", {})
    locale_config = locales.setdefault("es-ES", {})
    locale_config["name"] = env.invocation_name

    apis = manifest["manifest"].setdefault("apis", {}).setdefault("custom", {})
    endpoint = apis.setdefault("endpoint", {})
    if env.endpoint_url:
        endpoint["uri"] = env.endpoint_url
    return manifest


def render_interaction_model(payload: dict[str, Any], env: AlexaEnv) -> dict[str, Any]:
    model = json.loads(json.dumps(payload))
    language_model = model.setdefault("interactionModel", {}).setdefault("languageModel", {})
    language_model["invocationName"] = env.invocation_name
    return model


def create_clients() -> tuple[AlexaEnv, SmapiClient]:
    env = load_environment()
    lwa = LwaClient(env)
    token_payload = lwa.get_access_token()
    access_token = token_payload.get("access_token")
    if not access_token:
        raise AlexaConfigError("La respuesta de LWA no contiene access_token")
    return env, SmapiClient(access_token)


def require_skill_id(env: AlexaEnv) -> str:
    if not env.skill_id:
        raise AlexaConfigError("Define ALEXA_SKILL_ID en .env para esta operacion")
    return env.skill_id


def cmd_auth_test(_: argparse.Namespace) -> int:
    env = load_environment()
    try:
        token_payload = LwaClient(env).get_access_token()
        expires_in = token_payload.get("expires_in")
        print(json.dumps({"ok": True, "expires_in": expires_in}, ensure_ascii=True, indent=2))
        return 0
    except AlexaConfigError as exc:
        message = str(exc)
        if "unauthorized_client" in message:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "unauthorized_client",
                        "hint": (
                            "El refresh token actual no pertenece a este client_id/client_secret "
                            "o no fue emitido para este security profile. "
                            "Genera un refresh token nuevo con ASK CLI y guardalo en .env."
                        ),
                    },
                    ensure_ascii=True,
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 2
        raise


def cmd_auth_doctor(_: argparse.Namespace) -> int:
    env = load_environment()
    payload = {
        "client_id_present": bool(env.lwa_client_id),
        "client_secret_present": bool(env.lwa_client_secret),
        "refresh_token_present": bool(env.lwa_refresh_token),
        "skill_id": env.skill_id,
        "vendor_id": env.vendor_id,
    }
    try:
        token_payload = LwaClient(env).get_access_token()
        payload["auth_test"] = {
            "ok": True,
            "expires_in": token_payload.get("expires_in"),
        }
    except AlexaConfigError as exc:
        payload["auth_test"] = {
            "ok": False,
            "error": str(exc),
        }
        if "unauthorized_client" in str(exc):
            payload["next_step"] = [
                "Genera un refresh token nuevo con ASK CLI para este security profile.",
                "Guarda el refresh token resultante en .env como ALEXA_LWA_REFRESH_TOKEN.",
                "Vuelve a ejecutar `uv run python tools/alexa_sync.py auth-test`.",
            ]
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    env, smapi = create_clients()
    payload = {
        "skill_id": env.skill_id,
        "skill_stage": env.skill_stage,
        "endpoint_url": env.endpoint_url,
        "vendor_id": env.vendor_id,
    }
    if env.skill_id:
        payload["skill_status"] = smapi.get_skill_status(env.skill_id, env.skill_stage)
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0


def cmd_list_skills(_: argparse.Namespace) -> int:
    _, smapi = create_clients()
    print(json.dumps(smapi.list_skills_for_vendor(), ensure_ascii=True, indent=2))
    return 0


def cmd_push_manifest(args: argparse.Namespace) -> int:
    env, smapi = create_clients()
    skill_id = require_skill_id(env)
    config = load_repo_config(Path(args.config))
    manifest_path = ROOT_DIR / config["skill_package_path"]
    manifest = render_manifest(read_json(manifest_path), env)
    result = smapi.update_skill_manifest(skill_id, env.skill_stage, manifest)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


def cmd_push_model(args: argparse.Namespace) -> int:
    env, smapi = create_clients()
    skill_id = require_skill_id(env)
    config = load_repo_config(Path(args.config))
    locale = args.locale
    locale_map = config.get("interaction_model", {})
    relative_path = locale_map.get(locale)
    if not relative_path:
        raise AlexaConfigError(f"No hay interaction model configurado para {locale}")
    model_path = ROOT_DIR / relative_path
    model = render_interaction_model(read_json(model_path), env)
    description = (
        config.get("interaction_model_description")
        or f"Actualizacion del interaction model para {locale}."
    )
    result = smapi.update_interaction_model(skill_id, env.skill_stage, locale, model, description)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


def cmd_build_model(args: argparse.Namespace) -> int:
    return cmd_push_model(args)


def cmd_build_status(args: argparse.Namespace) -> int:
    env, smapi = create_clients()
    skill_id = require_skill_id(env)
    status = smapi.get_skill_status(skill_id, env.skill_stage)
    interaction_model_status = (((status or {}).get("interactionModel") or {}).get(args.locale) or {})
    print(json.dumps(interaction_model_status, ensure_ascii=True, indent=2))
    return 0


def cmd_get_model(args: argparse.Namespace) -> int:
    env, smapi = create_clients()
    skill_id = require_skill_id(env)
    model = smapi.get_interaction_model(skill_id, env.skill_stage, args.locale)
    print(json.dumps(model, ensure_ascii=True, indent=2))
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    env = load_environment()
    config = load_repo_config(Path(args.config))
    manifest_path = ROOT_DIR / config["skill_package_path"]
    manifest = render_manifest(read_json(manifest_path), env)
    locale_map = config.get("interaction_model", {})

    print("# Manifest")
    print(json.dumps(manifest, ensure_ascii=True, indent=2))
    for locale, relative_path in locale_map.items():
        print(f"# Interaction Model {locale}")
        model = render_interaction_model(read_json(ROOT_DIR / relative_path), env)
        print(json.dumps(model, ensure_ascii=True, indent=2))
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    env, smapi = create_clients()
    skill_id = require_skill_id(env)
    started = smapi.start_simulation(skill_id, env.skill_stage, args.utterance, args.locale)
    simulation_id = (started.get("id") or "").strip()
    if not simulation_id:
        print(json.dumps(started, ensure_ascii=True, indent=2))
        return 0

    result = started
    for _ in range(args.poll_attempts):
        if result.get("status") in {"SUCCESSFUL", "FAILED"}:
            break
        import time
        time.sleep(args.poll_interval)
        result = smapi.get_simulation(skill_id, env.skill_stage, simulation_id)

    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Herramienta config-as-code para skill Alexa")
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="Ruta al fichero de configuracion del skill",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("auth-test", help="Valida LWA con refresh token").set_defaults(func=cmd_auth_test)
    subparsers.add_parser("auth-doctor", help="Diagnostica credenciales LWA").set_defaults(func=cmd_auth_doctor)
    subparsers.add_parser("status", help="Muestra estado basico del skill").set_defaults(func=cmd_status)
    subparsers.add_parser("list-skills", help="Lista skills del vendor").set_defaults(func=cmd_list_skills)
    subparsers.add_parser("push-manifest", help="Sube el manifest del skill").set_defaults(func=cmd_push_manifest)

    push_model = subparsers.add_parser("push-model", help="Sube el interaction model de un locale")
    push_model.add_argument("--locale", default="es-ES")
    push_model.set_defaults(func=cmd_push_model)

    build_model = subparsers.add_parser("build-model", help="Lanza build del interaction model")
    build_model.add_argument("--locale", default="es-ES")
    build_model.set_defaults(func=cmd_build_model)

    build_status = subparsers.add_parser("build-status", help="Consulta estado del build del modelo")
    build_status.add_argument("--locale", default="es-ES")
    build_status.set_defaults(func=cmd_build_status)

    get_model = subparsers.add_parser("get-model", help="Descarga el interaction model publicado")
    get_model.add_argument("--locale", default="es-ES")
    get_model.set_defaults(func=cmd_get_model)

    simulate = subparsers.add_parser("simulate", help="Lanza una simulacion remota del skill")
    simulate.add_argument("--locale", default="es-ES")
    simulate.add_argument("--utterance", required=True)
    simulate.add_argument("--poll-attempts", type=int, default=10)
    simulate.add_argument("--poll-interval", type=float, default=1.0)
    simulate.set_defaults(func=cmd_simulate)

    subparsers.add_parser("render", help="Renderiza artefactos con valores del entorno").set_defaults(func=cmd_render)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except AlexaConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
