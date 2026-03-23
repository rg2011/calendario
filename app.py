from flask import Flask, render_template, request, url_for, jsonify, send_from_directory, make_response
from datetime import datetime, timedelta, date, timezone
from urllib.parse import urlencode
from urllib.request import urlopen
from functools import wraps
from hashlib import sha256
from threading import Lock, Thread
import calendar
import json
import logging
import os
import time

from dotenv import load_dotenv
from models import db, DayWeekRule, CustomShift

load_dotenv()

SECRET_PATH = os.environ.get('CALENDARIO_SECRET_PATH', '').strip().strip('/')
if not SECRET_PATH:
    raise RuntimeError('Debes definir CALENDARIO_SECRET_PATH en el entorno o en .env')
if '/' in SECRET_PATH:
    raise RuntimeError('CALENDARIO_SECRET_PATH debe ser un único segmento de ruta, sin "/"')

app = Flask(__name__, static_folder=None)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///calendar.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.logger.setLevel(logging.INFO)

db.init_app(app)

PEOPLE = ['Juanmi', 'Rafa', 'Ana']
HOLIDAY_API_URL = 'https://datos.juntadeandalucia.es/api/v0/work-calendar/get/search_calendar'
HOLIDAY_API_PROVINCE = 'SEVILLA'
HOLIDAY_API_MUNICIPALITY = 'SEVILLA'
HOLIDAY_CACHE_VERSION = 'junta-v2'
HOLIDAY_API_TIMEOUT_SECONDS = 8
HOLIDAY_REFRESH_INITIAL_DELAY_SECONDS = 2
HOLIDAY_REFRESH_MAX_BACKOFF_SECONDS = 30
HOLIDAY_REFRESH_SUCCESS_INTERVAL_SECONDS = 6 * 60 * 60
holiday_cache = {}
holiday_cache_lock = Lock()
holiday_refresh_thread = None
holiday_refresh_thread_lock = Lock()

MONTH_NAMES_ES = {
    1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio',
    7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
}


class AppState:
    """Mantiene versiones en memoria para revalidación HTTP condicional."""

    def __init__(self):
        boot_time = self._now()
        self._versions = {
            'app': boot_time,
            'data': boot_time,
            'holidays': boot_time,
        }

    def _now(self):
        return datetime.now(timezone.utc)

    def touch(self, *names):
        current_time = self._now()
        for name in names:
            self._versions[name] = current_time

    def touch_data(self):
        self.touch('data')

    def touch_holidays(self):
        self.touch('holidays')

    def last_modified(self, *names):
        version_names = names or ('app',)
        return max(self._versions[name] for name in version_names)

    def etag_for(self, resource_key, *names):
        payload = [str(resource_key)]
        for name in names:
            payload.append(f'{name}={self._versions[name].isoformat(timespec="microseconds")}')
        digest = sha256('|'.join(payload).encode('utf-8')).hexdigest()
        return f'calendario-{digest}'

    def is_not_modified(self, etag, last_modified):
        if_none_match = request.headers.get('If-None-Match')
        if if_none_match:
            candidate_tags = {item.strip() for item in if_none_match.split(',') if item.strip()}
            return '*' in candidate_tags or etag in candidate_tags or f'"{etag}"' in candidate_tags

        if_modified_since = request.if_modified_since
        if if_modified_since is not None:
            last_modified_utc = last_modified.astimezone(timezone.utc).replace(microsecond=0)
            if if_modified_since >= last_modified_utc:
                return True

        return False

    def cached_view(self, resource_builder, version_names, cache_control='private, no-cache'):
        def decorator(view_func):
            @wraps(view_func)
            def wrapped(*args, **kwargs):
                resource_key = resource_builder(*args, **kwargs)
                last_modified = self.last_modified(*version_names)
                etag = self.etag_for(resource_key, *version_names)

                if self.is_not_modified(etag, last_modified):
                    response = make_response('', 304)
                else:
                    response = make_response(view_func(*args, **kwargs))

                response.set_etag(etag)
                response.last_modified = last_modified
                response.headers['Cache-Control'] = cache_control
                return response

            return wrapped

        return decorator


app_state = AppState()


def get_week_start(target_date):
    """Devuelve el lunes de la semana de una fecha."""
    return target_date - timedelta(days=target_date.weekday())


def get_default_shift_for_day(shift_date):
    """
    Obtiene el turno por defecto de un día según su regla.
    Retorna la persona o None si no hay asignación aplicable.
    """
    day_of_week = shift_date.weekday()  # 0=lunes, 6=domingo
    rule = DayWeekRule.query.filter_by(day_of_week=day_of_week).first()

    if not rule:
        return None

    if rule.algorithm == 'fijo':
        return rule.person_fijo

    if rule.algorithm == 'rotatorio':
        if not rule.rotation_order or not rule.rotation_start_date:
            return None

        people_list = [p.strip() for p in rule.rotation_order.split(',') if p.strip()]
        if len(people_list) != 3:
            return None

        start_week = get_week_start(rule.rotation_start_date)
        shift_week = get_week_start(shift_date)

        if shift_week < start_week:
            return None

        weeks_diff = (shift_week - start_week).days // 7
        person_index = weeks_diff % len(people_list)
        return people_list[person_index]

    return None


def get_previous_month(year, month):
    """Devuelve el mes anterior como tupla (year, month)."""
    if month == 1:
        return year - 1, 12
    return year, month - 1


def get_next_month(year, month):
    """Devuelve el mes siguiente como tupla (year, month)."""
    if month == 12:
        return year + 1, 1
    return year, month + 1


def serialize_rule(rule):
    """Serializa una regla para respuestas JSON o plantillas."""
    return {
        'id': rule.id,
        'day_of_week': rule.day_of_week,
        'algorithm': rule.algorithm,
        'person_fijo': rule.person_fijo,
        'rotation_order': rule.rotation_order,
        'rotation_start_date': rule.rotation_start_date.isoformat() if rule.rotation_start_date else None,
    }


def month_date_range(year, month):
    """Devuelve la primera y última fecha de un mes."""
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def extract_holiday_rows(payload):
    """Normaliza la respuesta de la API a una lista de registros."""
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        for key in ('results', 'items', 'records', 'data'):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        for value in payload.values():
            if isinstance(value, list) and all(isinstance(item, dict) for item in value):
                return value

    return []


def parse_holiday_date(holiday):
    """Extrae la fecha del registro con cierta tolerancia a variantes de clave."""
    raw_date = holiday.get('dateformat') or holiday.get('startDate') or holiday.get('date')
    if not raw_date:
        return None

    if isinstance(raw_date, int):
        raw_date = str(raw_date)

    if not isinstance(raw_date, str):
        return None

    raw_date = raw_date.strip()
    for candidate in (raw_date[:10], raw_date):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue

    for fmt in ('%Y%m%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(raw_date, fmt).date()
        except ValueError:
            continue

    return None


def extract_holiday_name(holiday):
    """Obtiene el nombre visible del festivo desde la API de la Junta."""
    for key in ('description', 'event', 'name', 'title'):
        value = holiday.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return 'Festivo'


def fetch_holidays_from_api(year):
    """
    Consulta la API oficial de la Junta y devuelve un dict por fecha con nombres y ámbitos.
    Solo se usa para el año en curso.
    """
    params = {
        'province': HOLIDAY_API_PROVINCE,
        'municipality': HOLIDAY_API_MUNICIPALITY,
        'year': str(year),
    }
    url = f'{HOLIDAY_API_URL}?{urlencode(params)}'
    app.logger.info('Consultando API de festivos: %s', url)

    try:
        with urlopen(url, timeout=HOLIDAY_API_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                app.logger.warning('Respuesta no satisfactoria al consultar festivos: %s', response.status)
                return {}
            payload = json.loads(response.read().decode('utf-8'))
    except Exception as exc:
        app.logger.warning(
            'Error consultando la API de festivos para %s: %s: %s',
            year,
            type(exc).__name__,
            exc,
        )
        return {}

    rows = extract_holiday_rows(payload)
    app.logger.info('API de festivos %s: %s registros brutos recibidos', year, len(rows))

    holidays_by_date = {}
    for holiday in rows:
        holiday_date = parse_holiday_date(holiday)
        holiday_name = extract_holiday_name(holiday)
        holiday_type = holiday.get('type') or 'LABORAL'
        if not holiday_date or not holiday_name:
            continue

        holiday_entry = holidays_by_date.setdefault(
            holiday_date.isoformat(),
            {'names': [], 'scopes': []}
        )
        if holiday_name not in holiday_entry['names']:
            holiday_entry['names'].append(holiday_name)
        if holiday_type not in holiday_entry['scopes']:
            holiday_entry['scopes'].append(holiday_type)

    app.logger.info(
        'Festivos anualizados %s: %s fechas unicas (%s)',
        year,
        len(holidays_by_date),
        ', '.join(
            f'{holiday_date}={holiday_info["names"]}'
            for holiday_date, holiday_info in sorted(holidays_by_date.items())
        ) or 'sin resultados'
    )
    return holidays_by_date


def build_month_holiday_cache(year, year_holidays):
    """Construye la caché mensual completa a partir de los festivos anualizados."""
    monthly_cache = {}

    for month in range(1, 13):
        month_start, month_end = month_date_range(year, month)
        monthly_cache[(HOLIDAY_CACHE_VERSION, year, month)] = {
            holiday_date: holiday_info
            for holiday_date, holiday_info in year_holidays.items()
            if month_start <= date.fromisoformat(holiday_date) <= month_end
        }

    return monthly_cache


def get_year_cache_key(year):
    return (HOLIDAY_CACHE_VERSION, year, 'full_year')


def get_month_cache_key(year, month):
    return (HOLIDAY_CACHE_VERSION, year, month)


def get_cached_year_holidays(year):
    with holiday_cache_lock:
        return holiday_cache.get(get_year_cache_key(year))


def update_holiday_cache(year, year_holidays):
    with holiday_cache_lock:
        year_cache_key = get_year_cache_key(year)
        current_year_holidays = holiday_cache.get(year_cache_key)
        if current_year_holidays == year_holidays:
            return False

        holiday_cache[year_cache_key] = year_holidays
        holiday_cache.update(build_month_holiday_cache(year, year_holidays))

    app_state.touch_holidays()
    return True


def refresh_holiday_cache_for_year(year):
    """Intenta refrescar la caché anual de festivos y devuelve True si tuvo éxito."""
    if year != date.today().year:
        app.logger.info('Se omite la recarga de festivos para %s porque no es el año en curso', year)
        return False

    year_holidays = fetch_holidays_from_api(year)
    if not year_holidays:
        app.logger.warning('No se pudieron obtener festivos para %s', year)
        return False

    updated = update_holiday_cache(year, year_holidays)
    if updated:
        app.logger.info('Caché anual de festivos actualizada para %s: %s fechas', year, len(year_holidays))
    else:
        app.logger.info('La caché anual de festivos para %s ya estaba al día', year)
    return True


def calendar_cache_key(year, month):
    return f'calendar:{year:04d}-{month:02d}'


def current_month_cache_key():
    today = date.today()
    return calendar_cache_key(today.year, today.month)


def settings_cache_key():
    return 'settings'


def holiday_refresh_worker():
    """Mantiene la caché de festivos actualizada sin bloquear peticiones."""
    retry_delay = HOLIDAY_REFRESH_INITIAL_DELAY_SECONDS

    while True:
        current_year = date.today().year
        has_cache = get_cached_year_holidays(current_year) is not None

        success = refresh_holiday_cache_for_year(current_year)
        if success:
            retry_delay = HOLIDAY_REFRESH_INITIAL_DELAY_SECONDS
            time.sleep(HOLIDAY_REFRESH_SUCCESS_INTERVAL_SECONDS)
            continue

        if has_cache:
            time.sleep(HOLIDAY_REFRESH_SUCCESS_INTERVAL_SECONDS)
            continue

        app.logger.info(
            'Reintentando recarga de festivos para %s en %s segundos',
            current_year,
            retry_delay,
        )
        time.sleep(retry_delay)
        retry_delay = min(retry_delay * 2, HOLIDAY_REFRESH_MAX_BACKOFF_SECONDS)


def ensure_holiday_refresh_worker():
    global holiday_refresh_thread

    with holiday_refresh_thread_lock:
        if holiday_refresh_thread and holiday_refresh_thread.is_alive():
            return

        holiday_refresh_thread = Thread(
            target=holiday_refresh_worker,
            name='holiday-refresh',
            daemon=True,
        )
        holiday_refresh_thread.start()
        app.logger.info('Worker de recarga de festivos iniciado')


def get_month_holidays(year, month):
    """
    Devuelve los festivos de un mes usando caché en memoria.
    Solo consulta la API para meses del año en curso.
    """
    if year != date.today().year:
        return {}

    cache_key = get_month_cache_key(year, month)
    with holiday_cache_lock:
        month_holidays = holiday_cache.get(cache_key)

    if month_holidays is None:
        app.logger.info('Festivos %s-%02d no disponibles en cache; devolviendo calendario sin festivos', year, month)
        return {}

    app.logger.info(
        'Festivos %s-%02d obtenidos de cache mensual: %s fechas',
        year,
        month,
        len(month_holidays)
    )
    return month_holidays


def get_holidays_for_dates(dates_to_check):
    """Obtiene festivos para todas las fechas visibles del calendario."""
    holidays = {}
    visible_months = sorted({(day.year, day.month) for day in dates_to_check})

    for year, month in visible_months:
        holidays.update(get_month_holidays(year, month))

    return holidays


def get_month_days_full(year, month):
    """Retorna una lista de objetos dict con fecha, día de semana y mes (prev/current/next)"""
    days_list = []
    
    # Agregar últimos días del mes anterior
    first_day_weekday = datetime(year, month, 1).weekday()  # 0=lunes
    if first_day_weekday > 0:
        prev_year, prev_month = get_previous_month(year, month)
        
        prev_days_in_month = calendar.monthrange(prev_year, prev_month)[1]
        for day in range(prev_days_in_month - first_day_weekday + 1, prev_days_in_month + 1):
            days_list.append({
                'date': date(prev_year, prev_month, day),
                'day_num': day,
                'month_type': 'prev'
            })
    
    # Agregar días del mes actual
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        days_list.append({
            'date': date(year, month, day),
            'day_num': day,
            'month_type': 'current'
        })
    
    # Agregar primeros días del mes siguiente
    total_days_shown = len(days_list)
    if total_days_shown % 7 != 0:
        days_to_add = 7 - (total_days_shown % 7)
        next_year, next_month = get_next_month(year, month)
        
        for day in range(1, days_to_add + 1):
            days_list.append({
                'date': date(next_year, next_month, day),
                'day_num': day,
                'month_type': 'next'
            })
    
    return days_list


def get_shift_for_day(shift_date):
    """
    Obtiene el turno asignado para un día específico.
    Primero verifica si hay customización, luego aplica la regla.
    Retorna tupla: (person, is_custom)
    """
    # Verificar si hay turno customizado
    default_person = get_default_shift_for_day(shift_date)
    custom = CustomShift.query.filter_by(shift_date=shift_date).first()
    if custom:
        return custom.person, custom.person != default_person

    return default_person, False


def render_calendar(year, month):
    # Validar mes y año
    if month < 1 or month > 12:
        today = date.today()
        month = today.month
        year = today.year

    today = date.today()
    prev_year, prev_month = get_previous_month(year, month)
    next_year, next_month = get_next_month(year, month)
    
    # Obtener días del mes
    days = get_month_days_full(year, month)
    visible_holidays = get_holidays_for_dates(day['date'] for day in days)
    app.logger.info(
        'Render calendario %s-%02d con %s festivos detectados en dias visibles',
        year,
        month,
        len(visible_holidays)
    )
    
    # Obtener turnos para cada día
    for day in days:
        default_person = get_default_shift_for_day(day['date'])
        person, is_custom = get_shift_for_day(day['date'])
        holiday_info = visible_holidays.get(day['date'].isoformat())
        day['person'] = person
        day['default_person'] = default_person
        day['is_custom'] = is_custom
        day['is_today'] = day['date'] == today
        day['holiday_name'] = ' · '.join(holiday_info['names']) if holiday_info else None
        day['is_holiday'] = bool(holiday_info)
    
    # Agrupar en semanas
    weeks = [days[index:index + 7] for index in range(0, len(days), 7)]
    
    # Información del mes
    month_name = MONTH_NAMES_ES[month]
    month_options = [
        {'value': month_number, 'label': MONTH_NAMES_ES[month_number]}
        for month_number in range(1, 13)
    ]
    current_year = today.year
    year_options = sorted({current_year - 1, current_year, current_year + 1, year})

    context = {
        'year': year,
        'month': month,
        'month_name': month_name,
        'month_options': month_options,
        'year_options': year_options,
        'holiday_reference_year': current_year,
        'weeks': weeks,
        'days_of_week': ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'],
        'prev_url': url_for('calendar_view', year=prev_year, month=prev_month),
        'next_url': url_for('calendar_view', year=next_year, month=next_month),
        'people': PEOPLE,
    }
    
    return render_template('calendar.html', **context)


@app.route(f'/{SECRET_PATH}/')
@app_state.cached_view(lambda: current_month_cache_key(), ('data', 'holidays'))
def index():
    today = date.today()
    return render_calendar(today.year, today.month)


@app.route(f'/{SECRET_PATH}/calendar/<int:year>/<int:month>')
@app_state.cached_view(calendar_cache_key, ('data', 'holidays'))
def calendar_view(year, month):
    return render_calendar(year, month)


@app.route(f'/{SECRET_PATH}/manifest.webmanifest')
def web_app_manifest():
    manifest = {
        'id': url_for('index'),
        'name': 'Calendario de Turnos',
        'short_name': 'Calendario',
        'description': 'Calendario mensual de turnos con reglas, sobrescrituras y festivos de Sevilla.',
        'lang': 'es-ES',
        'start_url': url_for('index'),
        'scope': url_for('index'),
        'display': 'standalone',
        'orientation': 'portrait',
        'background_color': '#5b8def',
        'theme_color': '#31475f',
        'icons': [
            {
                'src': url_for('secret_static', filename='icons/icon-192.png'),
                'sizes': '192x192',
                'type': 'image/png',
                'purpose': 'any'
            },
            {
                'src': url_for('secret_static', filename='icons/icon-512.png'),
                'sizes': '512x512',
                'type': 'image/png',
                'purpose': 'any'
            },
            {
                'src': url_for('secret_static', filename='icons/icon-512.png'),
                'sizes': '512x512',
                'type': 'image/png',
                'purpose': 'maskable'
            }
        ]
    }
    return app.response_class(
        json.dumps(manifest, ensure_ascii=False),
        mimetype='application/manifest+json'
    )


@app.route(f'/{SECRET_PATH}/api/rules', methods=['GET', 'POST'])
def manage_rules():
    if request.method == 'GET':
        rules = DayWeekRule.query.order_by(DayWeekRule.day_of_week).all()
        return jsonify([serialize_rule(rule) for rule in rules])

    data = request.get_json() or {}
    day_of_week = data.get('day_of_week')
    algorithm = data.get('algorithm')

    rule = DayWeekRule.query.filter_by(day_of_week=day_of_week).first()
    if not rule:
        rule = DayWeekRule()
        rule.day_of_week = day_of_week

    rule.algorithm = algorithm

    if algorithm == 'fijo':
        rule.person_fijo = data.get('person_fijo')
        rule.rotation_order = None
        rule.rotation_start_date = None
    elif algorithm == 'rotatorio':
        rule.person_fijo = None
        rule.rotation_order = data.get('rotation_order')
        start_date_str = data.get('rotation_start_date')
        rule.rotation_start_date = (
            datetime.fromisoformat(start_date_str).date() if start_date_str else None
        )

    db.session.add(rule)
    db.session.commit()
    app_state.touch_data()

    return jsonify({'success': True, 'id': rule.id})


@app.route(f'/{SECRET_PATH}/api/custom-shift', methods=['POST'])
def set_custom_shift():
    data = request.get_json()
    shift_date_str = data.get('shift_date')
    person = data.get('person')
    
    if not shift_date_str or not person:
        return jsonify({'success': False, 'error': 'Invalid data'}), 400
    
    shift_date = datetime.fromisoformat(shift_date_str).date()
    
    custom = CustomShift.query.filter_by(shift_date=shift_date).first()
    
    if person == 'clear':
        if custom:
            db.session.delete(custom)
            db.session.commit()
            app_state.touch_data()
    else:
        if not custom:
            custom = CustomShift()
            custom.shift_date = shift_date
        custom.person = person
        db.session.add(custom)
        db.session.commit()
        app_state.touch_data()
    
    return jsonify({'success': True})


@app.route(f'/{SECRET_PATH}/settings')
@app_state.cached_view(lambda: settings_cache_key(), ('data',))
def settings():
    """Página para configurar las reglas"""
    days_of_week = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    rules = DayWeekRule.query.all()

    rules_dict = {rule.day_of_week: serialize_rule(rule) for rule in rules}
    
    context = {
        'days_of_week': days_of_week,
        'rules_dict': rules_dict,
        'people': PEOPLE,
    }
    
    return render_template('settings.html', **context)


@app.route(f'/{SECRET_PATH}/static/<path:filename>')
def secret_static(filename):
    return send_from_directory(os.path.join(app.root_path, 'static'), filename)


@app.before_request
def create_tables():
    db.create_all()
    ensure_holiday_refresh_worker()


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s [%(name)s] %(message)s'
    )
    host = os.environ.get('FLASK_RUN_HOST', '127.0.0.1')
    port = int(os.environ.get('FLASK_RUN_PORT', '5000'))
    debug = os.environ.get('FLASK_DEBUG', '').strip().lower() in {'1', 'true', 'yes', 'on'}
    app.logger.info('Rutas publicadas bajo el prefijo secreto /%s', SECRET_PATH)
    app.logger.info('Escuchando en http://%s:%s/%s', host, port, SECRET_PATH)
    with app.app_context():
        db.create_all()
    ensure_holiday_refresh_worker()
    app.run(host=host, port=port, debug=debug)
