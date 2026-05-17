from flask import Flask, render_template, request, url_for, jsonify, send_from_directory
from datetime import datetime, date
import json
import logging
import os

from src.alexa import New as NewAlexaHandler
from dotenv import load_dotenv
from src.absences import New as NewAbsenceService, serialize_absence
from src.calendar import New as NewCalendarService
from src.holidays import New as NewHolidayProvider
from src.httpcache import (
    New as NewHttpCache,
    absences_cache_key,
    calendar_cache_key,
    current_month_cache_key,
    settings_cache_key,
)
from src.models import db, Absence
from src.shifts import New as NewShiftService, serialize_rule

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
ALEXA_SKILL_ID = os.environ.get('ALEXA_SKILL_ID', '').strip()

app_state = NewHttpCache()
absence_service = NewAbsenceService(people=PEOPLE, cache_state=app_state)
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


@app.route(f'/{SECRET_PATH}/')
@app_state.cached_view(lambda: current_month_cache_key(), ('data', 'holidays'), include_current_day=True)
def index():
    today = date.today()
    context = calendar_service.build_context(
        today.year,
        today.month,
        calendar_url_builder=lambda year, month: url_for('calendar_view', year=year, month=month),
    )
    return render_template('calendar.html', **context)


@app.route(f'/{SECRET_PATH}/calendar/<int:year>/<int:month>')
@app_state.cached_view(calendar_cache_key, ('data', 'holidays'), include_current_day=True)
def calendar_view(year, month):
    context = calendar_service.build_context(
        year,
        month,
        calendar_url_builder=lambda target_year, target_month: url_for(
            'calendar_view',
            year=target_year,
            month=target_month,
        ),
    )
    return render_template('calendar.html', **context)


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
        rules = shift_service.list_rules()
        return jsonify([serialize_rule(rule) for rule in rules])

    payload, status = shift_service.save_rule(request.get_json() or {})
    return jsonify(payload), status


@app.route(f'/{SECRET_PATH}/api/custom-shift', methods=['POST'])
def set_custom_shift():
    payload, status = shift_service.set_custom_shift(request.get_json() or {})
    return jsonify(payload), status


def ensure_custom_shift_schema():
    """Asegura que custom_shifts tenga note y permita person=NULL."""
    inspector = db.inspect(db.engine)
    if 'custom_shifts' not in inspector.get_table_names():
        return

    columns = inspector.get_columns('custom_shifts')
    column_names = {column['name'] for column in columns}
    person_column = next((column for column in columns if column['name'] == 'person'), None)
    note_exists = 'note' in column_names
    person_allows_null = bool(person_column and person_column.get('nullable', False))

    if note_exists and person_allows_null:
        return

    with db.engine.begin() as connection:
        connection.exec_driver_sql(
            '''
            CREATE TABLE custom_shifts_new (
                id INTEGER PRIMARY KEY,
                shift_date DATE NOT NULL UNIQUE,
                person VARCHAR(50),
                note TEXT,
                created_at DATETIME,
                updated_at DATETIME
            )
            '''
        )
        if note_exists:
            connection.exec_driver_sql(
                '''
                INSERT INTO custom_shifts_new (id, shift_date, person, note, created_at, updated_at)
                SELECT id, shift_date, person, note, created_at, updated_at
                FROM custom_shifts
                '''
            )
        else:
            connection.exec_driver_sql(
                '''
                INSERT INTO custom_shifts_new (id, shift_date, person, created_at, updated_at)
                SELECT id, shift_date, person, created_at, updated_at
                FROM custom_shifts
                '''
            )
        connection.exec_driver_sql('DROP TABLE custom_shifts')
        connection.exec_driver_sql('ALTER TABLE custom_shifts_new RENAME TO custom_shifts')
    app_state.touch_data()
    app.logger.info('Esquema actualizado: custom_shifts.person ahora permite NULL y note está disponible')


def ensure_absence_schema():
    """Asegura la clave primaria compuesta (person, start_date) en absences."""
    inspector = db.inspect(db.engine)
    if 'absences' not in inspector.get_table_names():
        return

    columns = {column['name'] for column in inspector.get_columns('absences')}
    primary_key = inspector.get_pk_constraint('absences').get('constrained_columns') or []
    expected_primary_key = ['person', 'start_date']

    if columns >= {'person', 'start_date', 'end_date'} and primary_key == expected_primary_key:
        return

    with db.engine.begin() as connection:
        connection.exec_driver_sql(
            '''
            CREATE TABLE absences_new (
                person VARCHAR(50) NOT NULL,
                start_date DATE NOT NULL,
                end_date DATE NOT NULL,
                created_at DATETIME,
                updated_at DATETIME,
                PRIMARY KEY (person, start_date)
            )
            '''
        )
        if 'absences' in inspector.get_table_names():
            if 'id' in columns:
                connection.exec_driver_sql(
                    '''
                    INSERT INTO absences_new (person, start_date, end_date, created_at, updated_at)
                    SELECT person, start_date, end_date, created_at, updated_at
                    FROM absences
                    '''
                )
            else:
                connection.exec_driver_sql(
                    '''
                    INSERT INTO absences_new (person, start_date, end_date, created_at, updated_at)
                    SELECT person, start_date, end_date, created_at, updated_at
                    FROM absences
                    '''
                )
            connection.exec_driver_sql('DROP TABLE absences')
        connection.exec_driver_sql('ALTER TABLE absences_new RENAME TO absences')
    app_state.touch_data()
    app.logger.info('Esquema actualizado: tabla absences migrada a clave primaria compuesta')


@app.route(f'/{SECRET_PATH}/api/absences', methods=['GET', 'POST', 'DELETE'])
def manage_absences():
    if request.method == 'GET':
        absences = absence_service.list_absences()
        return jsonify([serialize_absence(absence) for absence in absences])

    data = request.get_json() or {}

    if request.method == 'DELETE':
        payload, status = absence_service.delete_absence(
            person=data.get('person') if isinstance(data.get('person'), str) else None,
            start_date_str=data.get('start_date') if isinstance(data.get('start_date'), str) else None,
        )
        return jsonify(payload), status

    payload, status = absence_service.save_absence(data)
    return jsonify(payload), status


@app.route(f'/{SECRET_PATH}/settings')
@app_state.cached_view(lambda: settings_cache_key(), ('data',))
def settings():
    """Página para configurar las reglas"""
    days_of_week = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
    rules = shift_service.list_rules()

    rules_dict = {rule.day_of_week: serialize_rule(rule) for rule in rules}
    
    context = {
        'days_of_week': days_of_week,
        'rules_dict': rules_dict,
        'people': sorted(PEOPLE),
    }
    
    return render_template('settings.html', **context)


@app.route(f'/{SECRET_PATH}/absences')
@app_state.cached_view(lambda: absences_cache_key(), ('data',))
def absences():
    absences_list = absence_service.list_absences()
    context = {
        'people': sorted(PEOPLE),
        'absences': [serialize_absence(absence) for absence in absences_list],
    }
    return render_template('absences.html', **context)


@app.route(f'/{SECRET_PATH}/static/<path:filename>')
def secret_static(filename):
    return send_from_directory(os.path.join(app.root_path, 'static'), filename)


@app.route(f'/{SECRET_PATH}/alexa', methods=['POST'])
def alexa_webhook():
    payload = request.get_json(silent=True) or {}
    if not alexa_handler.verify_skill_id(payload):
        app.logger.warning('Peticion Alexa rechazada por applicationId no valido')
        return jsonify({'message': 'Forbidden'}), 403

    request_type = ((payload.get('request') or {}).get('type') or '').strip()
    intent_name = (
        ((payload.get('request') or {}).get('intent') or {}).get('name') or ''
    ).strip()
    app.logger.info('Alexa request type=%s intent=%s', request_type or '-', intent_name or '-')
    return jsonify(alexa_handler.handle_request(payload))


@app.before_request
def create_tables():
    db.create_all()
    ensure_custom_shift_schema()
    ensure_absence_schema()
    holidays.ensure_refresh_worker()


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
        ensure_custom_shift_schema()
        ensure_absence_schema()
    holidays.ensure_refresh_worker()
    app.run(host=host, port=port, debug=debug)
