from logging import Logger

from src.httpcache import CacheState
from src.models import db


def ensure_custom_shift_schema(logger: Logger, cache_state: CacheState) -> None:
    """Asegura que `custom_shifts` tenga `note` y permita `person = NULL`."""
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
    cache_state.touch_data()
    logger.info('Esquema actualizado: custom_shifts.person ahora permite NULL y note está disponible')


def ensure_absence_schema(logger: Logger, cache_state: CacheState) -> None:
    """Asegura la clave primaria compuesta `(person, start_date)` en `absences`."""
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
            connection.exec_driver_sql(
                '''
                INSERT INTO absences_new (person, start_date, end_date, created_at, updated_at)
                SELECT person, start_date, end_date, created_at, updated_at
                FROM absences
                '''
            )
            connection.exec_driver_sql('DROP TABLE absences')
        connection.exec_driver_sql('ALTER TABLE absences_new RENAME TO absences')
    cache_state.touch_data()
    logger.info('Esquema actualizado: tabla absences migrada a clave primaria compuesta')
