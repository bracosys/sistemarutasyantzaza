#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Optimización de Rutas - Yantzaza
Aplicación Flask completa para gestión de rutas optimizadas
"""

import os
import logging
import json
from datetime import datetime, timedelta
from math import radians, cos, sin, asin, sqrt

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_required, current_user, login_user, logout_user, UserMixin
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('route_optimization.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# ================================
# INICIALIZACIÓN DE FLASK
# ================================

app = Flask(__name__)

# Configuración
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///route_optimization.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

# Crear directorio de uploads
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Inicializar extensiones
db = SQLAlchemy(app)
migrate = Migrate(app, db)
csrf = CSRFProtect(app)

# Configurar Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Por favor inicia sesión para acceder a esta página.'
login_manager.login_message_category = 'info'

# ================================
# MODELOS DE BASE DE DATOS
# ================================

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='driver')
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Relaciones
    completions = db.relationship('RouteCompletion', backref='driver', lazy=True)
    created_routes = db.relationship('Route', backref='creator', lazy=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def can_access_route(self, route):
        if self.role in ['admin', 'coordinator']:
            return True
        return route.active
    
    def __repr__(self):
        return f'<User {self.email}>'

class Vehicle(db.Model):
    __tablename__ = 'vehicles'
    
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(50), nullable=False)
    model = db.Column(db.String(50), nullable=False)
    year = db.Column(db.Integer)
    plate_number = db.Column(db.String(20), unique=True, nullable=False)
    status = db.Column(db.String(20), default='available')
    current_fuel_level = db.Column(db.Integer, default=4)
    current_driver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relaciones
    completions = db.relationship('RouteCompletion', backref='vehicle', lazy=True)
    current_driver = db.relationship('User', foreign_keys=[current_driver_id])
    
    def __repr__(self):
        return f'<Vehicle {self.brand} {self.model} - {self.plate_number}>'

class Route(db.Model):
    __tablename__ = 'routes'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    coordinates = db.Column(db.JSON)
    waypoints = db.Column(db.JSON)
    distance = db.Column(db.Float)
    estimated_time_minutes = db.Column(db.Integer)
    optimization_level = db.Column(db.String(20))
    original_distance = db.Column(db.Float)
    distance_saved_km = db.Column(db.Float, default=0)
    distance_saved_percent = db.Column(db.Float, default=0)
    estimated_time_saved_minutes = db.Column(db.Integer, default=0)
    loops_removed = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relaciones
    completions = db.relationship('RouteCompletion', backref='route', lazy=True)
    
    def __repr__(self):
        return f'<Route {self.name}>'

class RouteCompletion(db.Model):
    __tablename__ = 'route_completions'
    
    id = db.Column(db.Integer, primary_key=True)
    route_id = db.Column(db.Integer, db.ForeignKey('routes.id'), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicles.id'), nullable=False)
    status = db.Column(db.String(20), default='in_progress')
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    paused_at = db.Column(db.DateTime)
    resumed_at = db.Column(db.DateTime)
    fuel_start = db.Column(db.Integer, nullable=False)
    fuel_end = db.Column(db.Integer)
    fuel_consumption = db.Column(db.Float)
    notes = db.Column(db.Text)
    pause_reason = db.Column(db.String(255))
    
    # Ubicaciones
    start_latitude = db.Column(db.Float)
    start_longitude = db.Column(db.Float)
    end_latitude = db.Column(db.Float)
    end_longitude = db.Column(db.Float)
    current_latitude = db.Column(db.Float)
    current_longitude = db.Column(db.Float)
    last_position_update = db.Column(db.DateTime)
    
    # Datos de tracking
    track_data = db.Column(db.JSON)
    
    def __repr__(self):
        return f'<RouteCompletion {self.id}: {self.route.name} - {self.status}>'

class TrackingPoint(db.Model):
    __tablename__ = 'tracking_points'
    
    id = db.Column(db.Integer, primary_key=True)
    completion_id = db.Column(db.Integer, db.ForeignKey('route_completions.id'), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    accuracy = db.Column(db.Float, default=0)
    speed = db.Column(db.Float, default=0)
    heading = db.Column(db.Float, default=0)
    recorded_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    is_final_point = db.Column(db.Boolean, default=False)
    
    # Relaciones
    completion = db.relationship('RouteCompletion', backref=db.backref('tracking_points', lazy=True))
    
    def to_dict(self):
        return {
            'id': self.id,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'accuracy': self.accuracy,
            'speed': self.speed,
            'heading': self.heading,
            'recorded_at': self.recorded_at.isoformat(),
            'is_final_point': self.is_final_point
        }

# ================================
# CONFIGURACIÓN DE LOGIN
# ================================

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ================================
# FILTROS DE TEMPLATE
# ================================

@app.template_filter('distance_format')
def distance_format(distance):
    if distance is None:
        return 'N/A'
    return f"{distance:.1f} km"

@app.template_filter('datetime_format')
def datetime_format(dt, format='%d/%m/%Y %H:%M'):
    if dt is None:
        return 'N/A'
    return dt.strftime(format)

@app.template_filter('fuel_badge_class')
def fuel_badge_class(level):
    if level is None:
        return 'bg-secondary'
    elif level >= 3:
        return 'bg-success'
    elif level >= 2:
        return 'bg-warning'
    else:
        return 'bg-danger'

@app.template_filter('status_badge_class')
def status_badge_class(status):
    status_classes = {
        'completed': 'bg-success',
        'in_progress': 'bg-primary',
        'cancelled': 'bg-danger',
        'incomplete': 'bg-warning',
        'paused': 'bg-info'
    }
    return status_classes.get(status, 'bg-secondary')

@app.template_filter('status_text')
def status_text(status):
    status_texts = {
        'completed': 'Completada',
        'in_progress': 'En Progreso',
        'cancelled': 'Cancelada',
        'incomplete': 'Incompleta',
        'paused': 'Pausada'
    }
    return status_texts.get(status, status.title())

@app.template_filter('format_optimization_level')
def format_optimization_level(level):
    levels = {
        'none': 'Sin optimización',
        'basic': 'Básica',
        'medium': 'Intermedia',
        'advanced': 'Avanzada'
    }
    return levels.get(level, level.title() if level else 'N/A')

# ================================
# FUNCIONES AUXILIARES
# ================================

def calculate_distance(lat1, lng1, lat2, lng2):
    """Calcular distancia usando fórmula Haversine"""
    try:
        lng1, lat1, lng2, lat2 = map(radians, [lng1, lat1, lng2, lat2])
        dlng = lng2 - lng1
        dlat = lat2 - lat1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlng/2)**2
        distance = 2 * asin(sqrt(a)) * 6371  # Radio de la Tierra en km
        return distance
    except:
        return 0

def calculate_route_distance(coordinates):
    """Calcular distancia total de una ruta"""
    try:
        if not coordinates or len(coordinates) < 2:
            return 0
        
        total_distance = 0
        for i in range(1, len(coordinates)):
            lat1, lng1 = coordinates[i-1]
            lat2, lng2 = coordinates[i]
            total_distance += calculate_distance(lat1, lng1, lat2, lng2)
        
        return round(total_distance, 2)
    except Exception as e:
        logger.error(f"Error calculating route distance: {str(e)}")
        return 0

def get_driver_statistics(driver_id):
    """Calcular estadísticas del conductor"""
    try:
        completed_routes = RouteCompletion.query.filter_by(
            driver_id=driver_id,
            status='completed'
        ).count()
        
        completions_with_routes = db.session.query(RouteCompletion).join(Route).filter(
            RouteCompletion.driver_id == driver_id,
            RouteCompletion.status == 'completed',
            Route.distance.isnot(None)
        ).all()
        
        total_distance = sum(c.route.distance for c in completions_with_routes if c.route.distance)
        
        fuel_data = db.session.query(RouteCompletion).filter(
            RouteCompletion.driver_id == driver_id,
            RouteCompletion.status == 'completed',
            RouteCompletion.fuel_consumption.isnot(None)
        ).all()
        
        avg_efficiency = 0
        if fuel_data and total_distance > 0:
            total_fuel_consumed = sum(abs(c.fuel_consumption) for c in fuel_data if c.fuel_consumption)
            if total_fuel_consumed > 0:
                total_liters = total_fuel_consumed * 10
                avg_efficiency = total_distance / total_liters if total_liters > 0 else 0
        
        score = calculate_driver_score(driver_id, completed_routes, avg_efficiency)
        
        return {
            'completed_routes': completed_routes,
            'total_distance': round(total_distance, 1),
            'avg_efficiency': round(avg_efficiency, 1),
            'score': score
        }
    except Exception as e:
        logger.error(f"Error calculating driver statistics: {str(e)}")
        return {
            'completed_routes': 0,
            'total_distance': 0,
            'avg_efficiency': 0,
            'score': 0
        }

def calculate_driver_score(driver_id, completed_routes, avg_efficiency):
    """Calcular puntuación del conductor"""
    try:
        score = 0
        score += min(completed_routes * 2, 50)
        
        if avg_efficiency > 15:
            score += 30
        elif avg_efficiency > 12:
            score += 25
        elif avg_efficiency > 10:
            score += 20
        elif avg_efficiency > 8:
            score += 15
        elif avg_efficiency > 5:
            score += 10
        
        recent_completions = RouteCompletion.query.filter(
            RouteCompletion.driver_id == driver_id,
            RouteCompletion.started_at >= datetime.utcnow() - timedelta(days=30)
        ).all()
        
        if recent_completions:
            completed_ratio = len([c for c in recent_completions if c.status == 'completed']) / len(recent_completions)
            score += int(completed_ratio * 20)
        
        return min(score, 100)
    except Exception as e:
        logger.error(f"Error calculating driver score: {str(e)}")
        return 0

def get_optimized_routes_count():
    """Obtener contador de rutas optimizadas"""
    try:
        optimized_routes = Route.query.filter(
            Route.optimization_level.isnot(None),
            Route.optimization_level != 'none',
            Route.active == True
        ).all()
        
        total_km_saved = sum(route.distance_saved_km or 0 for route in optimized_routes)
        
        return {
            'count': len(optimized_routes),
            'total_km_saved': round(total_km_saved, 1),
            'routes': optimized_routes
        }
    except Exception as e:
        logger.error(f"Error getting optimized routes count: {str(e)}")
        return {'count': 0, 'total_km_saved': 0, 'routes': []}

def get_optimization_summary():
    """Obtener resumen de optimizaciones"""
    try:
        optimized_routes = Route.query.filter(
            Route.optimization_level.isnot(None),
            Route.optimization_level != 'none',
            Route.active == True
        ).all()
        
        if not optimized_routes:
            return {
                'total_routes_optimized': 0,
                'total_km_saved': 0,
                'total_time_saved_minutes': 0,
                'total_fuel_saved_liters': 0,
                'average_improvement_percent': 0,
                'best_optimization': None
            }
        
        total_km_saved = sum(route.distance_saved_km or 0 for route in optimized_routes)
        total_time_saved = sum(route.estimated_time_saved_minutes or 0 for route in optimized_routes)
        total_fuel_saved = total_km_saved * 0.1
        
        improvements = [route.distance_saved_percent for route in optimized_routes if route.distance_saved_percent]
        avg_improvement = sum(improvements) / len(improvements) if improvements else 0
        
        best_route = max(optimized_routes, key=lambda r: r.distance_saved_percent or 0, default=None)
        best_optimization = None
        if best_route:
            best_optimization = {
                'route_name': best_route.name,
                'improvement': best_route.distance_saved_percent,
                'km_saved': best_route.distance_saved_km
            }
        
        return {
            'total_routes_optimized': len(optimized_routes),
            'total_km_saved': round(total_km_saved, 1),
            'total_time_saved_minutes': int(total_time_saved),
            'total_fuel_saved_liters': round(total_fuel_saved, 1),
            'average_improvement_percent': round(avg_improvement, 1),
            'best_optimization': best_optimization
        }
    except Exception as e:
        logger.error(f"Error getting optimization summary: {str(e)}")
        return {
            'total_routes_optimized': 0,
            'total_km_saved': 0,
            'total_time_saved_minutes': 0,
            'total_fuel_saved_liters': 0,
            'average_improvement_percent': 0,
            'best_optimization': None
        }

def get_recent_completions():
    """Obtener completions recientes"""
    try:
        return RouteCompletion.query.filter_by(status='completed').order_by(
            RouteCompletion.completed_at.desc()
        ).limit(10).all()
    except Exception as e:
        logger.error(f"Error getting recent completions: {str(e)}")
        return []

# ================================
# RUTAS PRINCIPALES
# ================================

@app.route('/')
def index():
    """Página principal"""
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif current_user.role == 'coordinator':
            return redirect(url_for('coordinator_dashboard'))
        elif current_user.role == 'driver':
            return redirect(url_for('driver_dashboard'))
    
    return render_template('index.html')

# ================================
# RUTAS DE AUTENTICACIÓN
# ================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Página de login"""
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = bool(request.form.get('remember'))
        
        user = User.query.filter_by(email=email, active=True).first()
        
        if user and user.check_password(password):
            login_user(user, remember=remember)
            user.last_login = datetime.utcnow()
            db.session.commit()
            
            logger.info(f"User {email} logged in successfully")
            
            next_page = request.args.get('next')
            if next_page:
                return redirect(next_page)
            
            return redirect(url_for('index'))
        else:
            flash('Email o contraseña incorrectos', 'error')
    
    return render_template('auth/login.html')

@app.route('/logout')
@login_required
def logout():
    """Cerrar sesión"""
    logger.info(f"User {current_user.email} logged out")
    logout_user()
    flash('Has cerrado sesión correctamente', 'info')
    return redirect(url_for('index'))

# ================================
# RUTAS DEL DRIVER
# ================================

@app.route('/driver/dashboard')
@login_required
def driver_dashboard():
    """Dashboard principal del conductor"""
    try:
        if current_user.role != 'driver':
            flash('Acceso no autorizado', 'error')
            return redirect(url_for('index'))
        
        active_completion = RouteCompletion.query.filter_by(
            driver_id=current_user.id,
            status='in_progress'
        ).first()
        
        if active_completion:
            time_diff = datetime.utcnow() - active_completion.started_at
            if time_diff.total_seconds() > 86400:
                logger.warning(f"Active completion {active_completion.id} is older than 24 hours")
                active_completion.status = 'incomplete'
                active_completion.notes = 'Marcada como incompleta automáticamente por exceder 24 horas'
                db.session.commit()
                active_completion = None
        
        available_routes = []
        if not active_completion:
            available_routes = Route.query.filter_by(active=True).order_by(Route.name).all()
        
        available_vehicles = Vehicle.query.filter_by(
            status='available',
            active=True
        ).order_by(Vehicle.brand, Vehicle.model).all()
        
        driver_stats = get_driver_statistics(current_user.id)
        
        return render_template('driver/dashboard.html',
                             active_completion=active_completion,
                             available_routes=available_routes,
                             available_vehicles=available_vehicles,
                             driver_stats=driver_stats)
                             
    except Exception as e:
        logger.error(f"Error loading driver dashboard: {str(e)}")
        flash('Error cargando el dashboard', 'error')
        return redirect(url_for('index'))

@app.route('/driver/start_route', methods=['POST'])
@login_required
def start_route():
    """Iniciar una nueva ruta"""
    try:
        if current_user.role != 'driver':
            return jsonify({'error': 'No autorizado'}), 403
        
        existing_completion = RouteCompletion.query.filter_by(
            driver_id=current_user.id,
            status='in_progress'
        ).first()
        
        if existing_completion:
            return jsonify({'error': 'Ya tienes una ruta en progreso'}), 400
        
        data = request.get_json()
        route_id = data.get('route_id')
        vehicle_id = data.get('vehicle_id')
        fuel_start = data.get('fuel_start')
        
        if not all([route_id, vehicle_id, fuel_start]):
            return jsonify({'error': 'Datos incompletos'}), 400
        
        if fuel_start not in [1, 2, 3, 4]:
            return jsonify({'error': 'Nivel de combustible inválido'}), 400
        
        route = Route.query.filter_by(id=route_id, active=True).first()
        if not route:
            return jsonify({'error': 'Ruta no encontrada o inactiva'}), 404
        
        vehicle = Vehicle.query.filter_by(id=vehicle_id, status='available', active=True).first()
        if not vehicle:
            return jsonify({'error': 'Vehículo no disponible'}), 404
        
        completion = RouteCompletion(
            route_id=route_id,
            driver_id=current_user.id,
            vehicle_id=vehicle_id,
            status='in_progress',
            started_at=datetime.utcnow(),
            fuel_start=fuel_start
        )
        
        db.session.add(completion)
        
        vehicle.status = 'in_use'
        vehicle.current_driver_id = current_user.id
        
        db.session.commit()
        
        logger.info(f"Route {route_id} started by driver {current_user.id} with vehicle {vehicle_id}")
        
        return jsonify({
            'success': True,
            'message': f'Ruta "{route.name}" iniciada exitosamente',
            'completion_id': completion.id
        })
        
    except Exception as e:
        logger.error(f"Error starting route: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/driver/navigate/<int:completion_id>')
@login_required
def navigate_route(completion_id):
    """Página de navegación para el driver"""
    try:
        completion = RouteCompletion.query.filter_by(
            id=completion_id,
            driver_id=current_user.id,
            status='in_progress'
        ).first()
        
        if not completion:
            flash('Ruta no encontrada o no autorizada', 'error')
            return redirect(url_for('driver_dashboard'))
        
        route = completion.route
        vehicle = completion.vehicle
        
        return render_template('driver/navigate.html',
                             completion=completion,
                             route=route,
                             vehicle=vehicle)
                             
    except Exception as e:
        logger.error(f"Error loading navigation page: {str(e)}")
        flash('Error cargando la página de navegación', 'error')
        return redirect(url_for('driver_dashboard'))

@app.route('/driver/update_route_progress/<int:completion_id>', methods=['POST'])
@login_required
def update_route_progress(completion_id):
    """Actualizar progreso de la ruta con GPS"""
    try:
        completion = RouteCompletion.query.filter_by(
            id=completion_id,
            driver_id=current_user.id,
            status='in_progress'
        ).first()
        
        if not completion:
            return jsonify({'error': 'Ruta no encontrada o no autorizada'}), 404
        
        data = request.get_json()
        position = data.get('position', {})
        
        if not position or 'lat' not in position or 'lng' not in position:
            return jsonify({'error': 'Datos de posición inválidos'}), 400
        
        tracking_point = TrackingPoint(
            completion_id=completion_id,
            latitude=float(position['lat']),
            longitude=float(position['lng']),
            accuracy=position.get('accuracy', 0),
            recorded_at=datetime.utcnow(),
            speed=position.get('speed', 0),
            heading=position.get('heading', 0)
        )
        
        db.session.add(tracking_point)
        
        completion.last_position_update = datetime.utcnow()
        completion.current_latitude = float(position['lat'])
        completion.current_longitude = float(position['lng'])
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Posición actualizada correctamente',
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except ValueError as e:
        logger.error(f"Invalid position data: {str(e)}")
        return jsonify({'error': 'Datos de posición inválidos'}), 400
    except Exception as e:
        logger.error(f"Error updating route progress: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/driver/complete_route/<int:completion_id>', methods=['POST'])
@login_required
def complete_route(completion_id):
    """Completar una ruta"""
    try:
        completion = RouteCompletion.query.filter_by(
            id=completion_id,
            driver_id=current_user.id,
            status='in_progress'
        ).first()
        
        if not completion:
            return jsonify({'error': 'Ruta no encontrada o no autorizada'}), 404
        
        data = request.get_json()
        fuel_level = data.get('fuel_level')
        notes = data.get('notes', '').strip()
        final_position = data.get('final_position')
        trip_summary = data.get('trip_summary', {})
        
        if not fuel_level or fuel_level not in [1, 2, 3, 4]:
            return jsonify({'error': 'Nivel de combustible inválido'}), 400
        
        fuel_consumption = completion.fuel_start - fuel_level
        
        completion.status = 'completed'
        completion.completed_at = datetime.utcnow()
        completion.fuel_end = fuel_level
        completion.fuel_consumption = fuel_consumption
        completion.notes = notes
        
        if final_position and 'lat' in final_position and 'lng' in final_position:
            completion.end_latitude = float(final_position['lat'])
            completion.end_longitude = float(final_position['lng'])
            
            final_tracking = TrackingPoint(
                completion_id=completion_id,
                latitude=float(final_position['lat']),
                longitude=float(final_position['lng']),
                accuracy=final_position.get('accuracy', 0),
                recorded_at=datetime.utcnow(),
                is_final_point=True
            )
            db.session.add(final_tracking)
        
        if completion.vehicle:
            completion.vehicle.status = 'available'
            completion.vehicle.current_fuel_level = fuel_level
            completion.vehicle.current_driver_id = None
        
        tracking_points = TrackingPoint.query.filter_by(completion_id=completion_id).order_by(TrackingPoint.recorded_at).all()
        if tracking_points:
            track_data = []
            for point in tracking_points:
                track_data.append({
                    'lat': point.latitude,
                    'lng': point.longitude,
                    'timestamp': point.recorded_at.isoformat(),
                    'accuracy': point.accuracy,
                    'speed': point.speed
                })
            completion.track_data = json.dumps(track_data)
        
        db.session.commit()
        
        logger.info(f"Route completion {completion_id} completed successfully by driver {current_user.id}")
        
        return jsonify({
            'success': True,
            'message': f'Ruta completada exitosamente. Consumo: {abs(fuel_consumption)} cuartos de tanque.',
            'completion_id': completion_id,
            'fuel_consumption': fuel_consumption
        })
        
    except ValueError as e:
        logger.error(f"Invalid data in route completion: {str(e)}")
        return jsonify({'error': 'Datos inválidos'}), 400
    except Exception as e:
        logger.error(f"Error completing route: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/driver/cancel_route/<int:completion_id>', methods=['POST'])
@login_required
def cancel_route(completion_id):
    """Cancelar una ruta en progreso"""
    try:
        completion = RouteCompletion.query.filter_by(
            id=completion_id,
            driver_id=current_user.id,
            status='in_progress'
        ).first()
        
        if not completion:
            return jsonify({'error': 'Ruta no encontrada o no autorizada'}), 404
        
        data = request.get_json()
        reason = data.get('reason', '').strip()
        final_position = data.get('final_position')
        
        if not reason:
            return jsonify({'error': 'Debe proporcionar una razón para cancelar'}), 400
        
        completion.status = 'cancelled'
        completion.completed_at = datetime.utcnow()
        completion.notes = f"CANCELADA: {reason}"
        
        if final_position and 'lat' in final_position and 'lng' in final_position:
            completion.end_latitude = float(final_position['lat'])
            completion.end_longitude = float(final_position['lng'])
        
        if completion.vehicle:
            completion.vehicle.status = 'available'
            completion.vehicle.current_driver_id = None
        
        db.session.commit()
        
        logger.info(f"Route completion {completion_id} cancelled by driver {current_user.id}: {reason}")
        
        return jsonify({
            'success': True,
            'message': 'Ruta cancelada correctamente'
        })
        
    except Exception as e:
        logger.error(f"Error cancelling route: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/driver/route_history')
@login_required
def driver_route_history():
    """Historial de rutas del conductor"""
    try:
        if current_user.role != 'driver':
            flash('Acceso no autorizado', 'error')
            return redirect(url_for('index'))
        
        completions = RouteCompletion.query.filter_by(
            driver_id=current_user.id
        ).filter(
            RouteCompletion.status.in_(['completed', 'cancelled', 'incomplete'])
        ).order_by(RouteCompletion.started_at.desc()).limit(50).all()
        
        driver_stats = get_driver_statistics(current_user.id)
        
        return render_template('driver/route_history.html',
                             completions=completions,
                             driver_stats=driver_stats)
                             
    except Exception as e:
        logger.error(f"Error loading route history: {str(e)}")
        flash('Error cargando el historial', 'error')
        return redirect(url_for('driver_dashboard'))

# ================================
# RUTAS DE ADMINISTRADOR
# ================================

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    """Dashboard del administrador"""
    try:
        if current_user.role != 'admin':
            flash('Acceso no autorizado', 'error')
            return redirect(url_for('index'))
        
        total_users = User.query.filter_by(active=True).count()
        total_drivers = User.query.filter_by(role='driver', active=True).count()
        total_vehicles = Vehicle.query.filter_by(active=True).count()
        total_routes = Route.query.filter_by(active=True).count()
        
        completed_routes = RouteCompletion.query.filter_by(status='completed').count()
        in_progress_routes = RouteCompletion.query.filter_by(status='in_progress').count()
        
        recent_routes = Route.query.filter_by(active=True).order_by(Route.created_at.desc()).limit(10).all()
        recent_completions = RouteCompletion.query.filter(
            RouteCompletion.status.in_(['completed', 'cancelled'])
        ).order_by(RouteCompletion.completed_at.desc()).limit(5).all()
        
        optimized_routes = get_optimized_routes_count()
        optimization_summary = get_optimization_summary()
        
        return render_template('admin/dashboard.html',
                             total_users=total_users,
                             total_drivers=total_drivers,
                             total_vehicles=total_vehicles,
                             total_routes=total_routes,
                             completed_routes=completed_routes,
                             in_progress_routes=in_progress_routes,
                             recent_routes=recent_routes,
                             recent_completions=recent_completions,
                             optimized_routes=optimized_routes,
                             optimization_summary=optimization_summary)
                             
    except Exception as e:
        logger.error(f"Error loading admin dashboard: {str(e)}")
        flash('Error cargando el dashboard', 'error')
        return redirect(url_for('index'))

@app.route('/coordinator/dashboard')
@login_required
def coordinator_dashboard():
    """Dashboard del coordinador"""
    try:
        if current_user.role not in ['coordinator', 'admin']:
            flash('Acceso no autorizado', 'error')
            return redirect(url_for('index'))
        
        active_routes = RouteCompletion.query.filter_by(status='in_progress').count()
        completed_today = RouteCompletion.query.filter(
            RouteCompletion.status == 'completed',
            RouteCompletion.completed_at >= datetime.utcnow().date()
        ).count()
        
        available_drivers = User.query.filter_by(role='driver', active=True).count()
        available_vehicles = Vehicle.query.filter_by(status='available', active=True).count()
        
        recent_completions = RouteCompletion.query.filter(
            RouteCompletion.status.in_(['completed', 'cancelled'])
        ).order_by(RouteCompletion.completed_at.desc()).limit(10).all()
        
        return render_template('coordinator/dashboard.html',
                             active_routes=active_routes,
                             completed_today=completed_today,
                             available_drivers=available_drivers,
                             available_vehicles=available_vehicles,
                             recent_completions=recent_completions)
                             
    except Exception as e:
        logger.error(f"Error loading coordinator dashboard: {str(e)}")
        flash('Error cargando el dashboard', 'error')
        return redirect(url_for('index'))

# ================================
# RUTAS DE GESTIÓN
# ================================

@app.route('/routes/create', methods=['GET', 'POST'])
@login_required
def create_route():
    """Crear nueva ruta"""
    try:
        if current_user.role not in ['admin', 'coordinator']:
            flash('Acceso no autorizado', 'error')
            return redirect(url_for('index'))
        
        if request.method == 'POST':
            data = request.get_json()
            
            name = data.get('name', '').strip()
            description = data.get('description', '').strip()
            coordinates = data.get('coordinates', [])
            
            if not name:
                return jsonify({'error': 'El nombre es requerido'}), 400
            
            if not coordinates or len(coordinates) < 2:
                return jsonify({'error': 'Se requieren al menos 2 puntos'}), 400
            
            distance = calculate_route_distance(coordinates)
            
            route = Route(
                name=name,
                description=description,
                coordinates=coordinates,
                distance=distance,
                estimated_time_minutes=int(distance * 5),
                created_by=current_user.id
            )
            
            db.session.add(route)
            db.session.commit()
            
            logger.info(f"Route {name} created by user {current_user.id}")
            
            return jsonify({
                'success': True,
                'message': f'Ruta "{name}" creada exitosamente',
                'route_id': route.id
            })
        
        return render_template('routes/create.html')
        
    except Exception as e:
        logger.error(f"Error creating route: {str(e)}")
        if request.method == 'POST':
            db.session.rollback()
            return jsonify({'error': 'Error interno del servidor'}), 500
        else:
            flash('Error cargando la página', 'error')
            return redirect(url_for('index'))

@app.route('/routes/manage')
@login_required
def manage_routes():
    """Gestionar rutas"""
    try:
        if current_user.role not in ['admin', 'coordinator']:
            flash('Acceso no autorizado', 'error')
            return redirect(url_for('index'))
        
        routes = Route.query.order_by(Route.created_at.desc()).all()
        
        return render_template('routes/manage.html', routes=routes)
        
    except Exception as e:
        logger.error(f"Error loading routes management: {str(e)}")
        flash('Error cargando las rutas', 'error')
        return redirect(url_for('index'))

@app.route('/users/manage')
@login_required
def manage_users():
    """Gestionar usuarios"""
    try:
        if current_user.role != 'admin':
            flash('Acceso no autorizado', 'error')
            return redirect(url_for('index'))
        
        users = User.query.order_by(User.created_at.desc()).all()
        
        return render_template('admin/manage_users.html', users=users)
        
    except Exception as e:
        logger.error(f"Error loading users management: {str(e)}")
        flash('Error cargando los usuarios', 'error')
        return redirect(url_for('admin_dashboard'))

@app.route('/users/create', methods=['POST'])
@login_required
def create_user():
    """Crear nuevo usuario"""
    try:
        if current_user.role != 'admin':
            return jsonify({'error': 'No autorizado'}), 403
        
        data = request.get_json()
        
        email = data.get('email', '').strip().lower()
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        role = data.get('role', 'driver')
        password = data.get('password', '').strip()
        
        if not all([email, first_name, last_name, password]):
            return jsonify({'error': 'Todos los campos son requeridos'}), 400
        
        if role not in ['admin', 'coordinator', 'driver']:
            return jsonify({'error': 'Rol inválido'}), 400
        
        if User.query.filter_by(email=email).first():
            return jsonify({'error': 'El email ya está registrado'}), 400
        
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=role
        )
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        logger.info(f"User {email} created by admin {current_user.id}")
        
        return jsonify({
            'success': True,
            'message': f'Usuario {email} creado exitosamente'
        })
        
    except Exception as e:
        logger.error(f"Error creating user: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/vehicles/manage')
@login_required
def manage_vehicles():
    """Gestionar vehículos"""
    try:
        if current_user.role not in ['admin', 'coordinator']:
            flash('Acceso no autorizado', 'error')
            return redirect(url_for('index'))
        
        vehicles = Vehicle.query.order_by(Vehicle.created_at.desc()).all()
        
        return render_template('vehicles/manage.html', vehicles=vehicles)
        
    except Exception as e:
        logger.error(f"Error loading vehicles management: {str(e)}")
        flash('Error cargando los vehículos', 'error')
        return redirect(url_for('index'))

@app.route('/vehicles/create', methods=['POST'])
@login_required
def create_vehicle():
    """Crear nuevo vehículo"""
    try:
        if current_user.role not in ['admin', 'coordinator']:
            return jsonify({'error': 'No autorizado'}), 403
        
        data = request.get_json()
        
        brand = data.get('brand', '').strip()
        model = data.get('model', '').strip()
        year = data.get('year')
        plate_number = data.get('plate_number', '').strip().upper()
        
        if not all([brand, model, plate_number]):
            return jsonify({'error': 'Marca, modelo y placa son requeridos'}), 400
        
        if Vehicle.query.filter_by(plate_number=plate_number).first():
            return jsonify({'error': 'La placa ya está registrada'}), 400
        
        vehicle = Vehicle(
            brand=brand,
            model=model,
            year=year,
            plate_number=plate_number
        )
        
        db.session.add(vehicle)
        db.session.commit()
        
        logger.info(f"Vehicle {plate_number} created by user {current_user.id}")
        
        return jsonify({
            'success': True,
            'message': f'Vehículo {plate_number} creado exitosamente'
        })
        
    except Exception as e:
        logger.error(f"Error creating vehicle: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Error interno del servidor'}), 500

# ================================
# RUTAS DE API
# ================================

@app.route('/api/routes/<int:route_id>/preview')
@login_required
def get_route_preview(route_id):
    """Obtener datos de vista previa de una ruta"""
    try:
        route = Route.query.filter_by(id=route_id, active=True).first()
        if not route:
            return jsonify({'error': 'Ruta no encontrada'}), 404
        
        coordinates = []
        if route.coordinates:
            try:
                if isinstance(route.coordinates, str):
                    coordinates = json.loads(route.coordinates)
                elif isinstance(route.coordinates, list):
                    coordinates = route.coordinates
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Invalid coordinates format for route {route_id}")
        
        route_data = {
            'id': route.id,
            'name': route.name,
            'distance': route.distance,
            'coordinates': coordinates,
            'optimization_level': route.optimization_level,
            'estimated_time': route.estimated_time_minutes
        }
        
        return jsonify(route_data)
        
    except Exception as e:
        logger.error(f"Error getting route preview: {str(e)}")
        return jsonify({'error': 'Error interno del servidor'}), 500

@app.route('/api/vehicles/active-positions')
@login_required
def get_active_vehicle_positions():
    """Obtener posiciones de vehículos activos"""
    try:
        active_completions = RouteCompletion.query.filter_by(status='in_progress').all()
        
        vehicles_data = []
        for completion in active_completions:
            if completion.current_latitude and completion.current_longitude:
                status = 'offline'
                if completion.last_position_update:
                    time_diff = datetime.utcnow() - completion.last_position_update
                    if time_diff.total_seconds() < 300:
                        status = 'active'
                    elif time_diff.total_seconds() < 1800:
                        status = 'idle'
                
                vehicle_data = {
                    'vehicle_name': f"{completion.vehicle.brand} {completion.vehicle.model}",
                    'plate': completion.vehicle.plate_number,
                    'driver_name': f"{completion.driver.first_name} {completion.driver.last_name}",
                    'route_name': completion.route.name,
                    'lat': completion.current_latitude,
                    'lng': completion.current_longitude,
                    'status': status,
                    'fuel_level': completion.vehicle.current_fuel_level,
                    'started_at': completion.started_at.isoformat()
                }
                vehicles_data.append(vehicle_data)
        
        return jsonify(vehicles_data)
        
    except Exception as e:
        logger.error(f"Error getting active vehicle positions: {str(e)}")
        return jsonify([]), 500

@app.route('/api/report/preview/<report_type>')
@login_required
def preview_report_data(report_type):
    """Generar vista previa de datos del reporte"""
    try:
        if current_user.role not in ['admin', 'coordinator']:
            return jsonify({'error': 'No autorizado'}), 403
        
        report_data = {
            'report_type': report_type,
            'user': f"{current_user.first_name} {current_user.last_name}",
            'generated_at': datetime.utcnow().isoformat(),
            'summary': {
                'total_routes': Route.query.filter_by(active=True).count(),
                'completed_routes': RouteCompletion.query.filter_by(status='completed').count(),
                'active_drivers': User.query.filter_by(role='driver', active=True).count()
            }
        }
        
        if report_type == 'admin':
            report_data['optimization'] = get_optimization_summary()
        
        return jsonify(report_data)
        
    except Exception as e:
        logger.error(f"Error generating report preview: {str(e)}")
        return jsonify({'error': 'Error generando vista previa'}), 500

@app.route('/admin/download_report')
@login_required
def download_admin_report():
    """Descargar reporte administrativo"""
    try:
        if current_user.role != 'admin':
            flash('Acceso no autorizado', 'error')
            return redirect(url_for('index'))
        
        from services.pdf_generator import PDFReportGenerator
        
        data = {
            'metrics': {
                'total_users': User.query.filter_by(active=True).count(),
                'total_drivers': User.query.filter_by(role='driver', active=True).count(),
                'total_vehicles': Vehicle.query.filter_by(active=True).count(),
                'total_routes': Route.query.filter_by(active=True).count(),
                'completed_routes': RouteCompletion.query.filter_by(status='completed').count(),
                'in_progress_routes': RouteCompletion.query.filter_by(status='in_progress').count()
            },
            'optimization': get_optimization_summary(),
            'fuel': {
                'today_consumption': 0,
                'week_consumption': 0,
                'month_consumption': 0,
                'today_efficiency': 0,
                'week_efficiency': 0,
                'month_efficiency': 0
            },
            'vehicles': [],
            'drivers': [],
            'routes': []
        }
        
        generator = PDFReportGenerator()
        buffer = generator.generate_admin_report_with_optimization(
            data, 
            f"{current_user.first_name} {current_user.last_name}"
        )
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f'reporte_admin_{datetime.now().strftime("%Y%m%d_%H%M")}.pdf',
            mimetype='application/pdf'
        )
        
    except Exception as e:
        logger.error(f"Error generating admin report: {str(e)}")
        flash('Error generando el reporte', 'error')
        return redirect(url_for('admin_dashboard'))

@app.route('/completion_map/<int:completion_id>')
@login_required
def view_completion_map(completion_id):
    """Ver mapa de recorrido completado"""
    try:
        completion = RouteCompletion.query.get_or_404(completion_id)
        
        if current_user.role == 'driver' and completion.driver_id != current_user.id:
            flash('No autorizado', 'error')
            return redirect(url_for('driver_route_history'))
        elif current_user.role not in ['admin', 'coordinator', 'driver']:
            flash('No autorizado', 'error')
            return redirect(url_for('index'))
        
        track_data = []
        if completion.track_data:
            try:
                track_data = json.loads(completion.track_data)
            except json.JSONDecodeError:
                logger.warning(f"Invalid track data for completion {completion_id}")
        
        return render_template('maps/completion_track.html',
                             completion=completion,
                             track_data=track_data)
                             
    except Exception as e:
        logger.error(f"Error loading completion map: {str(e)}")
        flash('Error cargando el mapa', 'error')
        return redirect(url_for('index'))

# ================================
# MANEJO DE ERRORES
# ================================

@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('errors/500.html'), 500

@app.errorhandler(403)
def forbidden_error(error):
    return render_template('errors/403.html'), 403

# ================================
# COMANDOS CLI
# ================================

@app.cli.command()
def init_db():
    """Inicializar la base de datos"""
    db.create_all()
    print("Base de datos inicializada.")

@app.cli.command()
def create_admin():
    """Crear usuario administrador"""
    email = input("Email del administrador: ")
    password = input("Contraseña: ")
    first_name = input("Nombre: ")
    last_name = input("Apellido: ")
    
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        print("El usuario ya existe.")
        return
    
    admin = User(
        email=email,
        first_name=first_name,
        last_name=last_name,
        role='admin',
        active=True
    )
    admin.set_password(password)
    
    db.session.add(admin)
    db.session.commit()
    
    print(f"Usuario administrador {email} creado exitosamente.")

@app.cli.command()
def seed_data():
    """Poblar la base de datos con datos de ejemplo"""
    try:
        if not User.query.filter_by(email='admin@example.com').first():
            admin = User(
                email='admin@example.com',
                first_name='Admin',
                last_name='Sistema',
                role='admin'
            )
            admin.set_password('admin123')
            db.session.add(admin)
        
        if not User.query.filter_by(email='driver@example.com').first():
            driver = User(
                email='driver@example.com',
                first_name='Juan',
                last_name='Pérez',
                role='driver'
            )
            driver.set_password('driver123')
            db.session.add(driver)
        
        if not Vehicle.query.first():
            vehicles = [
                Vehicle(brand='Toyota', model='Hilux', year=2020, plate_number='ABC-1234'),
                Vehicle(brand='Chevrolet', model='D-Max', year=2019, plate_number='DEF-5678'),
                Vehicle(brand='Ford', model='Ranger', year=2021, plate_number='GHI-9012')
            ]
            for vehicle in vehicles:
                db.session.add(vehicle)
        
        if not Route.query.first():
            admin_user = User.query.filter_by(role='admin').first()
            if admin_user:
                routes = [
                    Route(
                        name='Ruta Centro Yantzaza',
                        description='Ruta que cubre el centro de Yantzaza',
                        coordinates=[[-3.8167, -78.7500], [-3.8200, -78.7450], [-3.8150, -78.7400]],
                        distance=5.2,
                        estimated_time_minutes=45,
                        created_by=admin_user.id
                    ),
                    Route(
                        name='Ruta Norte',
                        description='Ruta hacia el sector norte',
                        coordinates=[[-3.8167, -78.7500], [-3.8100, -78.7450], [-3.8050, -78.7400]],
                        distance=8.1,
                        estimated_time_minutes=60,
                        optimization_level='basic',
                        distance_saved_km=1.2,
                        distance_saved_percent=12.9,
                        created_by=admin_user.id
                    )
                ]
                for route in routes:
                    db.session.add(route)
        
        db.session.commit()
        print("Datos de ejemplo creados exitosamente.")
        
    except Exception as e:
        db.session.rollback()
        print(f"Error creando datos de ejemplo: {str(e)}")

# ================================
# CONTEXTO DE APLICACIÓN
# ================================

@app.context_processor
def inject_global_vars():
    """Inyectar variables globales en templates"""
    return {
        'now': datetime.utcnow(),
        'app_name': 'Sistema de Optimización de Rutas',
        'app_version': '1.0.0'
    }

# ================================
# CONFIGURACIÓN PARA PRODUCCIÓN
# ================================
app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=os.environ.get('FLASK_ENV') == 'development'
    )
