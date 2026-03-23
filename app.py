from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory
from datetime import datetime, timedelta, date
from urllib.parse import urlencode
from urllib.request import urlopen
import calendar
import json
import logging
import os

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
holiday_cache = {}

MONTH_NAMES_ES = {
    1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril', 5: 'Mayo', 6: 'Junio',
    7: 'Julio', 8: 'Agosto', 9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre'
}


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
        with urlopen(url, timeout=8) as response:
            if response.status != 200:
                app.logger.warning('Respuesta no satisfactoria al consultar festivos: %s', response.status)
                return {}
            payload = json.loads(response.read().decode('utf-8'))
    except Exception:
        app.logger.exception('Error consultando la API de festivos para %s', year)
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


def get_month_holidays(year, month):
    """
    Devuelve los festivos de un mes usando caché en memoria.
    Solo consulta la API para meses del año en curso.
    """
    if year != date.today().year:
        return {}

    cache_key = (HOLIDAY_CACHE_VERSION, year, month)
    if cache_key in holiday_cache:
        app.logger.info(
            'Festivos %s-%02d obtenidos de cache mensual: %s fechas',
            year,
            month,
            len(holiday_cache[cache_key])
        )
        return holiday_cache[cache_key]

    month_start, month_end = month_date_range(year, month)
    year_cache_key = (HOLIDAY_CACHE_VERSION, year, 'full_year')
    year_holidays = holiday_cache.get(year_cache_key)
    if year_holidays is None:
        app.logger.info('Cache anual de festivos vacia para %s, consultando API', year)
        year_holidays = fetch_holidays_from_api(year)
        if year_holidays:
            holiday_cache[year_cache_key] = year_holidays
            app.logger.info('Cache anual de festivos creada para %s', year)
        else:
            app.logger.warning('No se pudieron obtener festivos para %s', year)
            return {}
    else:
        app.logger.info('Festivos %s obtenidos de cache anual: %s fechas', year, len(year_holidays))

    month_holidays = {
        holiday_date: holiday_info
        for holiday_date, holiday_info in year_holidays.items()
        if month_start <= date.fromisoformat(holiday_date) <= month_end
    }
    holiday_cache[cache_key] = month_holidays
    app.logger.info(
        'Festivos para %s-%02d: %s',
        year,
        month,
        ', '.join(
            f'{holiday_date}={holiday_info["names"]}'
            for holiday_date, holiday_info in sorted(month_holidays.items())
        ) or 'sin festivos'
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


@app.route(f'/{SECRET_PATH}/')
def index():
    today = date.today()
    return redirect(url_for('calendar_view', year=today.year, month=today.month))


@app.route(f'/{SECRET_PATH}/calendar/<int:year>/<int:month>')
def calendar_view(year, month):
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
    
    context = {
        'year': year,
        'month': month,
        'month_name': month_name,
        'weeks': weeks,
        'days_of_week': ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom'],
        'prev_url': url_for('calendar_view', year=prev_year, month=prev_month),
        'next_url': url_for('calendar_view', year=next_year, month=next_month),
        'people': PEOPLE,
    }
    
    return render_template('calendar.html', **context)


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
        rule = DayWeekRule(day_of_week=day_of_week)

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
    else:
        if not custom:
            custom = CustomShift(shift_date=shift_date)
        custom.person = person
        db.session.add(custom)
        db.session.commit()
    
    return jsonify({'success': True})


@app.route(f'/{SECRET_PATH}/settings')
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
    app.run(host=host, port=port, debug=debug)
