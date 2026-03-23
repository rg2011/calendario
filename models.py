from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class DayWeekRule(db.Model):
    """Regla de asignación para cada día de la semana (0=lunes, 6=domingo)"""
    __tablename__ = 'day_week_rules'

    id = db.Column(db.Integer, primary_key=True)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=lunes, 6=domingo
    algorithm = db.Column(db.String(20), nullable=False)  # 'fijo' o 'rotatorio'
    person_fijo = db.Column(db.String(50))  # Para algoritmo 'fijo'

    # Para algoritmo 'rotatorio'
    rotation_order = db.Column(db.String(50))  # 'Juanmi,Rafa,Ana' formato
    rotation_start_date = db.Column(db.Date)  # Fecha inicial de rotación

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CustomShift(db.Model):
    """Turno customizado para un día específico"""
    __tablename__ = 'custom_shifts'

    id = db.Column(db.Integer, primary_key=True)
    shift_date = db.Column(db.Date, nullable=False, unique=True)
    person = db.Column(db.String(50), nullable=False)
    note = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Absence(db.Model):
    """Ausencia de una persona en un rango de fechas."""
    __tablename__ = 'absences'

    person = db.Column(db.String(50), primary_key=True)
    start_date = db.Column(db.Date, primary_key=True)
    end_date = db.Column(db.Date, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
