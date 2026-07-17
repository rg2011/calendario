import json
import logging
import os
from datetime import date

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    g,
    has_request_context,
    jsonify,
    render_template,
    request,
    send_from_directory,
    url_for,
)

from src.absences import New as NewAbsenceService
from src.absences import serialize_absence
from src.alexa import New as NewAlexaHandler
from src.bootstrap import initialize_runtime, register_startup
from src.calendar import New as NewCalendarService
from src.contacts import New as NewContactService
from src.holidays import New as NewHolidayProvider
from src.httpcache import (
    New as NewHttpCache,
)
from src.httpcache import (
    absences_cache_key,
    calendar_cache_key,
    contacts_cache_key,
    current_month_cache_key,
    settings_cache_key,
    week_cache_key,
)
from src.models import db
from src.shifts import New as NewShiftService
from src.shifts import serialize_rule

load_dotenv()

READ_WRITE = "read_write"
READ_ONLY = "read_only"
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def read_secret_path(env_name: str) -> str:
    """Lee y valida un secreto de ruta desde una variable de entorno."""
    secret_path = os.environ.get(env_name, "").strip().strip("/")
    if not secret_path:
        raise RuntimeError(f"Debes definir {env_name} en el entorno o en .env")
    if "/" in secret_path:
        raise RuntimeError(f'{env_name} debe ser un único segmento de ruta, sin "/"')
    return secret_path


SECRET_PATH = read_secret_path("CALENDARIO_SECRET_PATH")
READONLY_SECRET_PATH = read_secret_path("CALENDARIO_READONLY_SECRET_PATH")
if READONLY_SECRET_PATH == SECRET_PATH:
    raise RuntimeError(
        "CALENDARIO_READONLY_SECRET_PATH debe ser distinto de CALENDARIO_SECRET_PATH"
    )

app = Flask(__name__, static_folder=None)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///calendar.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.logger.setLevel(logging.INFO)

db.init_app(app)

PEOPLE = ["Juanmi", "Rafa", "Ana"]
ALEXA_SKILL_ID = os.environ.get("ALEXA_SKILL_ID", "").strip()

app_state = NewHttpCache()
absence_service = NewAbsenceService(people=PEOPLE, cache_state=app_state)
contact_service = NewContactService(cache_state=app_state)
holidays = NewHolidayProvider(logger=app.logger, cache_state=app_state)
shift_service = NewShiftService(
    people=PEOPLE,
    absence_service=absence_service,
    cache_state=app_state,
)
calendar_service = NewCalendarService(
    people=PEOPLE,
    logger=app.logger,
    absence_service=absence_service,
    holiday_provider=holidays,
    shift_service=shift_service,
)
alexa_handler = NewAlexaHandler(skill_id=ALEXA_SKILL_ID, shift_service=shift_service)


def current_secret_path() -> str:
    """Devuelve el secreto de la petición actual, usando read-only como fallback seguro."""
    if has_request_context():
        return getattr(g, "secret_path", READONLY_SECRET_PATH)
    return READONLY_SECRET_PATH


def current_access_mode() -> str:
    """Devuelve el modo de acceso actual, usando read-only como fallback seguro."""
    if has_request_context():
        return getattr(g, "access_mode", READ_ONLY)
    return READ_ONLY


def access_cache_key(resource_key: str) -> str:
    """Separa las claves de caché por modo de acceso."""
    return f"{current_access_mode()}:{resource_key}"


def endpoint_accepts_secret(endpoint: str) -> bool:
    """Indica si un endpoint registrado acepta el parámetro dinámico `secret`."""
    try:
        return any("secret" in rule.arguments for rule in app.url_map.iter_rules(endpoint))
    except KeyError:
        return False


def path_after_secret() -> str:
    """Devuelve la parte de la ruta posterior al primer segmento secreto."""
    path_parts = request.path.lstrip("/").split("/", 1)
    if len(path_parts) != 2:
        return ""
    return path_parts[1]


@app.before_request
def resolve_secret_access():
    """Resuelve el modo de acceso de la petición y bloquea escrituras read-only."""
    secret = request.path.lstrip("/").split("/", 1)[0]
    if secret == SECRET_PATH:
        g.secret_path = SECRET_PATH
        g.access_mode = READ_WRITE
    elif secret == READONLY_SECRET_PATH:
        g.secret_path = READONLY_SECRET_PATH
        g.access_mode = READ_ONLY
    else:
        abort(404)

    if g.access_mode == READ_ONLY and request.endpoint == "alexa_webhook":
        abort(404)

    if g.access_mode == READ_ONLY and request.method in WRITE_METHODS:
        if path_after_secret().startswith("api/"):
            return jsonify({"success": False, "error": "Ruta de solo lectura"}), 403
        abort(403)


@app.url_defaults
def add_secret_to_urls(endpoint: str, values: dict[str, object]) -> None:
    """Propaga el secreto actual al construir URLs internas con `url_for`."""
    if "secret" not in values and endpoint_accepts_secret(endpoint):
        values["secret"] = current_secret_path()


@app.route("/<secret>/")
@app_state.cached_view(
    lambda secret: access_cache_key(current_month_cache_key()),
    ("data", "holidays"),
    include_current_day=True,
)
def index(secret):
    today = date.today()
    context = calendar_service.build_context(
        today.year,
        today.month,
        calendar_url_builder=lambda year, month: url_for("calendar_view", year=year, month=month),
        include_notes=current_access_mode() != READ_ONLY,
    )
    return render_template("calendar.html", **context)


@app.route("/<secret>/calendar/<int:year>/<int:month>")
@app_state.cached_view(
    lambda secret, year, month: access_cache_key(calendar_cache_key(year, month)),
    ("data", "holidays"),
    include_current_day=True,
)
def calendar_view(secret, year, month):
    context = calendar_service.build_context(
        year,
        month,
        calendar_url_builder=lambda target_year, target_month: url_for(
            "calendar_view",
            year=target_year,
            month=target_month,
        ),
        include_notes=current_access_mode() != READ_ONLY,
    )
    return render_template("calendar.html", **context)


@app.route("/<secret>/manifest.webmanifest")
def web_app_manifest(secret):
    manifest = {
        "id": url_for("index"),
        "name": "Calendario de Turnos",
        "short_name": "Calendario",
        "description": (
            "Calendario mensual de turnos con reglas, sobrescrituras y festivos de Sevilla."
        ),
        "lang": "es-ES",
        "start_url": url_for("index"),
        "scope": url_for("index"),
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#5b8def",
        "theme_color": "#31475f",
        "icons": [
            {
                "src": url_for("secret_static", filename="icons/icon-192.png"),
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": url_for("secret_static", filename="icons/icon-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": url_for("secret_static", filename="icons/icon-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable",
            },
        ],
    }
    return app.response_class(
        json.dumps(manifest, ensure_ascii=False), mimetype="application/manifest+json"
    )


@app.route("/<secret>/easy-mode.webmanifest")
def easy_mode_manifest(secret):
    easy_mode_url = url_for("easy_mode")
    manifest = {
        "id": easy_mode_url,
        "name": "Calendario de Turnos — modo sencillo",
        "short_name": "Turnos",
        "description": "Vista sencilla de turnos y marcación.",
        "lang": "es-ES",
        "start_url": easy_mode_url,
        "scope": easy_mode_url,
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#5b8def",
        "theme_color": "#31475f",
        "icons": [
            {
                "src": url_for("secret_static", filename="icons/icon-192.png"),
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any",
            },
            {
                "src": url_for("secret_static", filename="icons/icon-512.png"),
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any",
            },
        ],
    }
    return app.response_class(
        json.dumps(manifest, ensure_ascii=False), mimetype="application/manifest+json"
    )


@app.route("/<secret>/api/rules", methods=["GET", "POST"])
def manage_rules(secret):
    if request.method == "GET":
        rules = shift_service.list_rules()
        return jsonify([serialize_rule(rule) for rule in rules])

    payload, status = shift_service.save_rule(request.get_json() or {})
    return jsonify(payload), status


@app.route("/<secret>/api/custom-shift", methods=["POST"])
def set_custom_shift(secret):
    payload, status = shift_service.set_custom_shift(request.get_json() or {})
    return jsonify(payload), status


@app.route("/<secret>/api/absences", methods=["GET", "POST", "DELETE"])
def manage_absences(secret):
    if request.method == "GET":
        absences = absence_service.list_absences()
        return jsonify([serialize_absence(absence) for absence in absences])

    data = request.get_json() or {}

    if request.method == "DELETE":
        payload, status = absence_service.delete_absence(
            person=data.get("person") if isinstance(data.get("person"), str) else None,
            start_date_str=data.get("start_date")
            if isinstance(data.get("start_date"), str)
            else None,
        )
        return jsonify(payload), status

    payload, status = absence_service.save_absence(data)
    return jsonify(payload), status


@app.route("/<secret>/api/contacts", methods=["GET", "POST"])
def manage_contacts(secret):
    if request.method == "GET":
        return jsonify(contact_service.contacts_by_shortcut())

    payload, status = contact_service.save_contacts(request.get_json() or {})
    return jsonify(payload), status


@app.route("/<secret>/settings")
@app_state.cached_view(lambda secret: access_cache_key(settings_cache_key()), ("data",))
def settings(secret):
    """Página para configurar las reglas"""
    days_of_week = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    rules = shift_service.list_rules()

    rules_dict = {rule.day_of_week: serialize_rule(rule) for rule in rules}

    context = {
        "days_of_week": days_of_week,
        "rules_dict": rules_dict,
        "people": sorted(PEOPLE),
    }

    return render_template("settings.html", **context)


@app.route("/<secret>/week")
@app_state.cached_view(lambda secret: access_cache_key(week_cache_key()), ("data",))
def week(secret):
    context = calendar_service.build_week_context(
        date.today(),
        include_notes=current_access_mode() != READ_ONLY,
    )
    context["contacts"] = contact_service.contacts_by_shortcut()
    return render_template("week.html", **context)


@app.route("/<secret>/easy")
@app_state.cached_view(lambda secret: access_cache_key(f"easy:{week_cache_key()}"), ("data",))
def easy_mode(secret):
    context = calendar_service.build_week_context(
        date.today(),
        include_notes=current_access_mode() != READ_ONLY,
    )
    context["contacts"] = contact_service.contacts_by_shortcut()
    context["easy_mode"] = True
    return render_template("week.html", **context)


@app.route("/<secret>/absences")
@app_state.cached_view(lambda secret: access_cache_key(absences_cache_key()), ("data",))
def absences(secret):
    absences_list = absence_service.list_absences()
    context = {
        "people": sorted(PEOPLE),
        "absences": [serialize_absence(absence) for absence in absences_list],
    }
    return render_template("absences.html", **context)


@app.route("/<secret>/contacts")
@app_state.cached_view(lambda secret: access_cache_key(contacts_cache_key()), ("data",))
def contacts(secret):
    return render_template("contacts.html", contacts=contact_service.contacts_by_shortcut())


@app.route("/<secret>/static/<path:filename>")
def secret_static(secret, filename):
    return send_from_directory(os.path.join(app.root_path, "static"), filename)


@app.route("/<secret>/alexa", methods=["POST"])
def alexa_webhook(secret):
    payload = request.get_json(silent=True) or {}
    if not alexa_handler.verify_skill_id(payload):
        app.logger.warning("Peticion Alexa rechazada por applicationId no valido")
        return jsonify({"message": "Forbidden"}), 403

    request_type = ((payload.get("request") or {}).get("type") or "").strip()
    intent_name = (((payload.get("request") or {}).get("intent") or {}).get("name") or "").strip()
    app.logger.info("Alexa request type=%s intent=%s", request_type or "-", intent_name or "-")
    return jsonify(alexa_handler.handle_request(payload))


register_startup(app, holidays, app_state)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    host = os.environ.get("FLASK_RUN_HOST", "127.0.0.1")
    port = int(os.environ.get("FLASK_RUN_PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
    app.logger.info(
        "Rutas publicadas bajo /%s y /%s en modo solo lectura",
        SECRET_PATH,
        READONLY_SECRET_PATH,
    )
    app.logger.info("Escuchando en http://%s:%s/%s", host, port, SECRET_PATH)
    with app.app_context():
        initialize_runtime(app, holidays, app_state)
    app.run(host=host, port=port, debug=debug)
