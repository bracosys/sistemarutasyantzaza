import os
import uuid
import json
import random
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory, send_file
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from services.route_optimizer import AdvancedRouteOptimizer

import gpxpy
import networkx as nx
from geopy.distance import geodesic
import folium

# Importar el generador de PDF (se creará después)
try:
    from services.pdf_generator import PDFReportGenerator
except ImportError:
    PDFReportGenerator = None
    print("Warning: PDF generator not available. Create services/pdf_generator.py")

# Inicialización de extensiones
db = SQLAlchemy()
login_manager = LoginManager()

# ==================== MODELOS DE BASE DE DATOS ====================

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    cedula = db.Column(db.String(20), unique=True, nullable=False)
    role = db.Column(db.String(20), default='driver')
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    driver_info = db.relationship('DriverInfo', backref='user', uselist=False, cascade="all, delete-orphan")
    routes_created = db.relationship('Route', backref='creator', lazy=True, foreign_keys='Route.creator_id')
    routes_driven = db.relationship('RouteCompletion', backref='driver', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    @property
    def is_admin(self):
        return self.role == 'admin'
    
    @property
    def is_technician(self):
        return self.role == 'technician'
    
    @property
    def is_coordinator(self):
        return self.role == 'coordinator'
    
    @property
    def is_driver(self):
        return self.role == 'driver'

    def __repr__(self):
        return f'<User {self.username}>'

class DriverInfo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    license_type = db.Column(db.String(20), nullable=False)
    active = db.Column(db.Boolean, default=True)
    vehicles = db.relationship('VehicleAssignment', backref='driver', lazy=True)

class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(100), nullable=False)
    model = db.Column(db.String(100), nullable=False)
    year = db.Column(db.Integer, nullable=False)
    plate_number = db.Column(db.String(20), unique=True, nullable=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    drivers = db.relationship('VehicleAssignment', backref='vehicle', lazy=True)

class VehicleAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('driver_info.id'), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    active = db.Column(db.Boolean, default=True)

class Route(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    file_path = db.Column(db.String(200), nullable=False)
    gpx_path = db.Column(db.String(200), nullable=True)
    start_point = db.Column(db.String(100), nullable=True)
    end_point = db.Column(db.String(100), nullable=True)
    distance = db.Column(db.Float, nullable=True)
    active = db.Column(db.Boolean, default=True)
    completions = db.relationship('RouteCompletion', backref='route', lazy=True)
    original_distance = db.Column(db.Float, nullable=True)  # Distancia original antes de optimizar
    distance_saved_km = db.Column(db.Float, nullable=True)  # Kilómetros ahorrados
    distance_saved_percent = db.Column(db.Float, nullable=True)  # Porcentaje de mejora
    estimated_time_saved_minutes = db.Column(db.Integer, nullable=True)  # Tiempo ahorrado en minutos
    optimization_level = db.Column(db.String(20), nullable=True)  # Nivel de optimización usado
    loops_removed = db.Column(db.Integer, nullable=True)  # Número de bucles eliminados
    points_reduced = db.Column(db.Integer, nullable=True)  # Puntos reducidos en la optimización
    
    completions = db.relationship('RouteCompletion', backref='route', lazy=True)

class RouteCompletion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    route_id = db.Column(db.Integer, db.ForeignKey('route.id'), nullable=False)
    driver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'), nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), default='pending')
    track_data = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    fuel_start = db.Column(db.Integer, nullable=True)
    fuel_end = db.Column(db.Integer, nullable=True)  
    fuel_consumption = db.Column(db.Integer, nullable=True)
    # NUEVO CAMPO PARA EL MAPA DEL RECORRIDO
    track_map_path = db.Column(db.String(200), nullable=True)
    vehicle = db.relationship('Vehicle', backref='route_completions')

# ==================== DECORADORES DE AUTORIZACIÓN ====================

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Debes iniciar sesión para acceder a esta página.', 'danger')
                return redirect(url_for('login'))
            
            if current_user.role not in roles:
                flash('No tienes permisos para acceder a esta página.', 'danger')
                return redirect(url_for('dashboard'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def admin_required(f):
    return role_required('admin')(f)

def technician_required(f):
    return role_required('admin', 'technician')(f)

def coordinator_required(f):
    return role_required('admin', 'coordinator')(f)

def driver_required(f):
    return role_required('admin', 'driver')(f)

# ==================== FUNCIONES AUXILIARES ====================

def load_gpx_points(file_path):
    with open(file_path, 'r') as gpx_file:
        gpx = gpxpy.parse(gpx_file)
    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points.append((point.latitude, point.longitude))
    return points

def optimize_route(file_paths):
    all_points = []
    for path in file_paths:
        all_points.extend(load_gpx_points(path))

    graph = nx.Graph()
    total_distance = 0
    
    for i in range(len(all_points) - 1):
        dist = geodesic(all_points[i], all_points[i + 1]).meters
        graph.add_edge(all_points[i], all_points[i + 1], weight=dist)
        total_distance += dist

    start = all_points[0]
    end = all_points[-1]
    
    try:
        optimal_path = nx.shortest_path(graph, source=start, target=end, weight='weight')
        return optimal_path, total_distance
    except nx.NetworkXNoPath:
        raise Exception("No se pudo encontrar una ruta entre los puntos de inicio y fin.")

# ==================== FUNCIONES PARA MÉTRICAS Y REPORTES ====================

def get_metrics_data():
    """Obtener datos consolidados de métricas"""
    try:
        total_users = User.query.filter_by(active=True).count()
        total_drivers = User.query.filter_by(role='driver', active=True).count()
        total_vehicles = Vehicle.query.filter_by(active=True).count()
        total_routes = Route.query.filter_by(active=True).count()
        completed_routes = RouteCompletion.query.filter_by(status='completed').count()
        in_progress_routes = RouteCompletion.query.filter_by(status='in_progress').count()
        
        month_start = datetime.now().date().replace(day=1)
        monthly_completions = RouteCompletion.query.filter(
            RouteCompletion.completed_at >= month_start,
            RouteCompletion.status == 'completed',
            RouteCompletion.fuel_consumption.isnot(None)
        ).all()
        
        monthly_fuel = sum([c.fuel_consumption * 40 for c in monthly_completions if c.fuel_consumption])
        total_distance = sum([c.route.distance / 1000 for c in monthly_completions if c.route and c.route.distance])
        avg_efficiency = (total_distance / (monthly_fuel / 40)) if monthly_fuel > 0 else 0
        
        return {
            'total_users': total_users,
            'total_drivers': total_drivers,
            'total_vehicles': total_vehicles,
            'total_routes': total_routes,
            'completed_routes': completed_routes,
            'in_progress_routes': in_progress_routes,
            'monthly_fuel': monthly_fuel,
            'avg_efficiency': round(avg_efficiency, 1)
        }
    except Exception as e:
        print(f"Error en get_metrics_data: {e}")
        return {}

def get_fuel_data():
    """Obtener datos detallados de combustible"""
    try:
        now = datetime.now()
        today = now.date()
        week_start = today - timedelta(days=today.weekday())
        month_start = today.replace(day=1)
        
        def get_completions_for_period(start_date):
            return RouteCompletion.query.filter(
                RouteCompletion.completed_at >= start_date,
                RouteCompletion.status == 'completed',
                RouteCompletion.fuel_consumption.isnot(None)
            ).all()
        
        def calculate_metrics(completions):
            if not completions:
                return {'consumption': 0, 'routes': 0, 'efficiency': 0}
            
            total_fuel = sum([c.fuel_consumption * 40 for c in completions if c.fuel_consumption])
            total_distance = sum([c.route.distance / 1000 for c in completions if c.route and c.route.distance])
            efficiency = (total_distance / (total_fuel / 40)) if total_fuel > 0 else 0
            
            return {
                'consumption': round(total_fuel, 1),
                'routes': len(completions),
                'efficiency': round(efficiency, 1)
            }
        
        today_metrics = calculate_metrics(get_completions_for_period(today))
        week_metrics = calculate_metrics(get_completions_for_period(week_start))
        month_metrics = calculate_metrics(get_completions_for_period(month_start))
        
        return {
            'today_consumption': today_metrics['consumption'],
            'today_routes': today_metrics['routes'],
            'today_efficiency': today_metrics['efficiency'],
            'week_consumption': week_metrics['consumption'],
            'week_routes': week_metrics['routes'],
            'week_efficiency': week_metrics['efficiency'],
            'month_consumption': month_metrics['consumption'],
            'month_routes': month_metrics['routes'],
            'month_efficiency': month_metrics['efficiency']
        }
    except Exception as e:
        print(f"Error en get_fuel_data: {e}")
        return {}

def get_vehicle_performance_data():
    """Obtener datos de rendimiento por vehículo"""
    try:
        month_start = datetime.now().date().replace(day=1)
        completions = RouteCompletion.query.filter(
            RouteCompletion.completed_at >= month_start,
            RouteCompletion.status == 'completed',
            RouteCompletion.fuel_consumption.isnot(None)
        ).all()
        
        vehicle_data = {}
        for completion in completions:
            if completion.vehicle:
                vehicle_key = completion.vehicle.id
                
                if vehicle_key not in vehicle_data:
                    vehicle_data[vehicle_key] = {
                        'vehicle_name': f"{completion.vehicle.brand} {completion.vehicle.model}",
                        'plate': completion.vehicle.plate_number,
                        'consumption': 0,
                        'routes': 0,
                        'total_distance': 0
                    }
                
                vehicle_data[vehicle_key]['consumption'] += (completion.fuel_consumption or 0) * 40
                vehicle_data[vehicle_key]['routes'] += 1
                if completion.route and completion.route.distance:
                    vehicle_data[vehicle_key]['total_distance'] += completion.route.distance
        
        result = []
        for vehicle in vehicle_data.values():
            efficiency = 0
            if vehicle['consumption'] > 0 and vehicle['total_distance'] > 0:
                km = vehicle['total_distance'] / 1000
                efficiency = km / (vehicle['consumption'] / 40)
            
            result.append({
                'vehicle_name': vehicle['vehicle_name'],
                'plate': vehicle['plate'],
                'consumption': round(vehicle['consumption'], 1),
                'routes': vehicle['routes'],
                'efficiency': round(efficiency, 1)
            })
        
        return sorted(result, key=lambda x: x['efficiency'], reverse=True)
    except Exception as e:
        print(f"Error en get_vehicle_performance_data: {e}")
        return []

def get_driver_performance_data():
    """Obtener datos de rendimiento por chofer"""
    try:
        month_start = datetime.now().date().replace(day=1)
        completions = RouteCompletion.query.filter(
            RouteCompletion.completed_at >= month_start,
            RouteCompletion.status == 'completed',
            RouteCompletion.fuel_consumption.isnot(None)
        ).all()
        
        driver_data = {}
        for completion in completions:
            if completion.driver:
                driver_key = completion.driver.id
                
                if driver_key not in driver_data:
                    driver_data[driver_key] = {
                        'driver': f"{completion.driver.first_name} {completion.driver.last_name}",
                        'consumption': 0,
                        'routes': 0,
                        'total_distance': 0,
                        'total_time': 0
                    }
                
                driver_data[driver_key]['consumption'] += (completion.fuel_consumption or 0) * 40
                driver_data[driver_key]['routes'] += 1
                
                if completion.route and completion.route.distance:
                    driver_data[driver_key]['total_distance'] += completion.route.distance
                
                if completion.started_at and completion.completed_at:
                    duration = (completion.completed_at - completion.started_at).total_seconds() / 3600
                    driver_data[driver_key]['total_time'] += duration
        
        result = []
        for driver in driver_data.values():
            efficiency = 0
            avg_time = 0
            
            if driver['consumption'] > 0 and driver['total_distance'] > 0:
                km = driver['total_distance'] / 1000
                efficiency = km / (driver['consumption'] / 40)
            
            if driver['routes'] > 0 and driver['total_time'] > 0:
                avg_time = driver['total_time'] / driver['routes']
            
            score = 0
            if efficiency > 0:
                score = min(100, (efficiency * 6) + (50 - (avg_time * 2)) if avg_time > 0 else efficiency * 6)
                score = max(0, score)
            
            result.append({
                'driver': driver['driver'],
                'consumption': round(driver['consumption'], 1),
                'routes': driver['routes'],
                'efficiency': round(efficiency, 1),
                'score': round(score)
            })
        
        return sorted(result, key=lambda x: x['score'], reverse=True)
    except Exception as e:
        print(f"Error en get_driver_performance_data: {e}")
        return []

def get_route_performance_data():
    """Obtener datos de rendimiento por ruta"""
    try:
        month_start = datetime.now().date().replace(day=1)
        completions = RouteCompletion.query.filter(
            RouteCompletion.completed_at >= month_start,
            RouteCompletion.status == 'completed',
            RouteCompletion.fuel_consumption.isnot(None)
        ).all()
        
        route_data = {}
        for completion in completions:
            if completion.route:
                route_key = completion.route.id
                
                if route_key not in route_data:
                    route_data[route_key] = {
                        'route': completion.route.name,
                        'total_consumption': 0,
                        'completions': 0,
                        'distance': completion.route.distance or 0
                    }
                
                route_data[route_key]['total_consumption'] += (completion.fuel_consumption or 0) * 40
                route_data[route_key]['completions'] += 1
        
        result = []
        for route in route_data.values():
            avg_consumption = 0
            if route['completions'] > 0:
                avg_consumption = route['total_consumption'] / route['completions']
            
            result.append({
                'route': route['route'],
                'avg_consumption': round(avg_consumption, 1),
                'completions': route['completions'],
                'distance': route['distance']
            })
        
        return sorted(result, key=lambda x: x['avg_consumption'], reverse=True)
    except Exception as e:
        print(f"Error en get_route_performance_data: {e}")
        return []
    

def generate_completion_map(completion):
    """Generar mapa visual del recorrido completado"""
    try:
        import folium
        import json
        from datetime import datetime
        import uuid
        import os
        
        if not completion.track_data:
            return None
        
        # Cargar datos del tracking
        track_points = json.loads(completion.track_data)
        
        if not track_points or len(track_points) < 2:
            return None
        
        # Crear el mapa centrado en el primer punto
        center_lat = track_points[0]['lat']
        center_lng = track_points[0]['lng']
        
        # Crear mapa con estilo profesional
        completion_map = folium.Map(
            location=[center_lat, center_lng],
            zoom_start=14,
            tiles='OpenStreetMap'
        )
        
        # Extraer coordenadas para la ruta
        route_coords = [(point['lat'], point['lng']) for point in track_points]
        
        # Agregar la línea del recorrido real
        folium.PolyLine(
            locations=route_coords,
            color='#e74c3c',  # Rojo para el recorrido real
            weight=4,
            opacity=0.8,
            popup=f'Recorrido Real - {completion.route.name}'
        ).add_to(completion_map)
        
        # Marcador de inicio (verde)
        folium.Marker(
            location=[track_points[0]['lat'], track_points[0]['lng']],
            popup=f'''
            <div style="min-width: 200px;">
                <h5>🚀 INICIO</h5>
                <p><strong>Ruta:</strong> {completion.route.name}</p>
                <p><strong>Conductor:</strong> {completion.driver.first_name} {completion.driver.last_name}</p>
                <p><strong>Vehículo:</strong> {completion.vehicle.brand} {completion.vehicle.model}</p>
                <p><strong>Placa:</strong> {completion.vehicle.plate_number}</p>
                <p><strong>Iniciado:</strong> {completion.started_at.strftime('%d/%m/%Y %H:%M')}</p>
                <p><strong>Combustible inicial:</strong> {completion.fuel_start}/4</p>
            </div>
            ''',
            icon=folium.Icon(color='green', icon='play', prefix='fa')
        ).add_to(completion_map)
        
        # Marcador de fin (rojo)
        folium.Marker(
            location=[track_points[-1]['lat'], track_points[-1]['lng']],
            popup=f'''
            <div style="min-width: 200px;">
                <h5>🏁 FIN</h5>
                <p><strong>Completado:</strong> {completion.completed_at.strftime('%d/%m/%Y %H:%M')}</p>
                <p><strong>Combustible final:</strong> {completion.fuel_end}/4</p>
                <p><strong>Consumo:</strong> {completion.fuel_consumption}/4 tanques</p>
                <p><strong>Duración:</strong> {str(completion.completed_at - completion.started_at).split('.')[0]}</p>
                {f"<p><strong>Notas:</strong> {completion.notes}</p>" if completion.notes else ""}
            </div>
            ''',
            icon=folium.Icon(color='red', icon='stop', prefix='fa')
        ).add_to(completion_map)
        
        # Agregar marcadores cada cierto número de puntos para mostrar progreso
        if len(track_points) > 4:
            interval = max(1, len(track_points) // 4)
            for i in range(interval, len(track_points) - 1, interval):
                point = track_points[i]
                timestamp = datetime.fromisoformat(point['timestamp']).strftime('%H:%M:%S')
                
                folium.CircleMarker(
                    location=[point['lat'], point['lng']],
                    radius=3,
                    popup=f'Punto de control - {timestamp}',
                    color='#3498db',
                    fillColor='#3498db',
                    fillOpacity=0.7
                ).add_to(completion_map)
        
        # Agregar información del recorrido en el mapa
        legend_html = f'''
        <div style="position: fixed; 
                    top: 10px; right: 10px; width: 300px; height: auto; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:14px; padding: 10px; border-radius: 5px;
                    box-shadow: 0 0 15px rgba(0,0,0,0.2);">
            <h4 style="margin-top: 0;">📊 Resumen del Recorrido</h4>
            <p><strong>Ruta:</strong> {completion.route.name}</p>
            <p><strong>Conductor:</strong> {completion.driver.first_name} {completion.driver.last_name}</p>
            <p><strong>Vehículo:</strong> {completion.vehicle.brand} {completion.vehicle.model} ({completion.vehicle.plate_number})</p>
            <p><strong>Fecha:</strong> {completion.completed_at.strftime('%d/%m/%Y')}</p>
            <p><strong>Duración:</strong> {str(completion.completed_at - completion.started_at).split('.')[0]}</p>
            <p><strong>Puntos registrados:</strong> {len(track_points)}</p>
            <p><strong>Combustible:</strong> {completion.fuel_start}/4 → {completion.fuel_end}/4</p>
            <p><strong>Consumo:</strong> {completion.fuel_consumption}/4 tanques</p>
            <hr>
            <p style="font-size: 12px; margin-bottom: 0;">
                🟢 Inicio &nbsp;&nbsp;&nbsp; 🔴 Fin &nbsp;&nbsp;&nbsp; 
                <span style="color: #e74c3c;">━━━</span> Recorrido real
            </p>
        </div>
        '''
        completion_map.get_root().html.add_child(folium.Element(legend_html))
        
        # Agregar la ruta planificada original si está disponible
        if completion.route.gpx_path and os.path.exists(completion.route.gpx_path):
            try:
                from services.route_optimizer import AdvancedRouteOptimizer
                optimizer = AdvancedRouteOptimizer()
                original_points = optimizer.load_gpx_points(completion.route.gpx_path)
                
                # Agregar la ruta original en color diferente
                folium.PolyLine(
                    locations=original_points,
                    color='#3498db',  # Azul para la ruta planificada
                    weight=2,
                    opacity=0.6,
                    dash_array='5, 5',
                    popup='Ruta Planificada Original'
                ).add_to(completion_map)
                
                # Actualizar la leyenda para incluir la ruta original
                legend_html = legend_html.replace(
                    '<span style="color: #e74c3c;">━━━</span> Recorrido real',
                    '<span style="color: #e74c3c;">━━━</span> Recorrido real &nbsp;&nbsp;&nbsp; <span style="color: #3498db;">┅┅┅</span> Ruta planificada'
                )
                
            except Exception as e:
                print(f"No se pudo cargar la ruta original: {e}")
        
        return completion_map
        
    except Exception as e:
        print(f"Error generando mapa de recorrido: {e}")
        return None



def get_recent_completions(limit=10):
    """Obtener recorridos completados recientes"""
    try:
        return RouteCompletion.query.filter_by(
            status='completed'
        ).order_by(
            RouteCompletion.completed_at.desc()
        ).limit(limit).all()
    except Exception as e:
        print(f"Error obteniendo recorridos recientes: {e}")
        return []
    

def get_optimized_routes_count():
    """Obtener rutas optimizadas de forma segura"""
    try:
        # Verificar si las columnas existen primero
        inspector = db.inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('route')]
        
        if 'distance_saved_km' in columns:
            # Las columnas existen, usar consulta normal
            optimized_routes = Route.query.filter(
                Route.active == True,
                Route.distance_saved_km.isnot(None),
                Route.distance_saved_km > 0
            ).all()
            
            total_km_saved = sum([route.distance_saved_km for route in optimized_routes])
            
            return {
                'count': len(optimized_routes),
                'total_km_saved': total_km_saved,
                'routes': optimized_routes
            }
        else:
            # Las columnas no existen, devolver valores por defecto
            print("Columnas de optimización no encontradas, usando valores por defecto")
            return {
                'count': 0,
                'total_km_saved': 0,
                'routes': []
            }
    except Exception as e:
        print(f"Error en get_optimized_routes_count: {e}")
        return {'count': 0, 'total_km_saved': 0, 'routes': []}

def get_optimization_summary():
    """Obtener resumen de optimizaciones de forma segura"""
    try:
        # Verificar si las columnas existen
        inspector = db.inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('route')]
        
        required_columns = ['distance_saved_km', 'distance_saved_percent', 'estimated_time_saved_minutes']
        columns_exist = all(col in columns for col in required_columns)
        
        if columns_exist:
            # Ejecutar lógica normal
            optimized_routes = Route.query.filter(
                Route.active == True,
                Route.distance_saved_km.isnot(None),
                Route.distance_saved_km > 0
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
            
            total_km_saved = sum([route.distance_saved_km for route in optimized_routes])
            total_time_saved = sum([route.estimated_time_saved_minutes or 0 for route in optimized_routes])
            
            # Calcular combustible ahorrado
            def calculate_fuel_savings(km_saved):
                if not km_saved or km_saved <= 0:
                    return 0
                liters_per_100km = 8
                return (km_saved * liters_per_100km) / 100
            
            total_fuel_saved = sum([calculate_fuel_savings(route.distance_saved_km) for route in optimized_routes])
            
            # Mejora promedio
            improvements = [route.distance_saved_percent for route in optimized_routes if route.distance_saved_percent]
            average_improvement = sum(improvements) / len(improvements) if improvements else 0
            
            # Mejor optimización
            best_route = max(optimized_routes, key=lambda r: r.distance_saved_percent or 0) if optimized_routes else None
            
            return {
                'total_routes_optimized': len(optimized_routes),
                'total_km_saved': round(total_km_saved, 2),
                'total_time_saved_minutes': int(total_time_saved),
                'total_fuel_saved_liters': round(total_fuel_saved, 1),
                'average_improvement_percent': round(average_improvement, 1),
                'best_optimization': {
                    'route_name': best_route.name,
                    'improvement': round(best_route.distance_saved_percent or 0, 1),
                    'km_saved': round(best_route.distance_saved_km or 0, 2)
                } if best_route else None
            }
        else:
            # Columnas no existen, devolver valores por defecto
            print("Columnas de optimización no encontradas, usando valores por defecto")
            return {
                'total_routes_optimized': 0,
                'total_km_saved': 0,
                'total_time_saved_minutes': 0,
                'total_fuel_saved_liters': 0,
                'average_improvement_percent': 0,
                'best_optimization': None
            }
    except Exception as e:
        print(f"Error en get_optimization_summary: {e}")
        return {
            'total_routes_optimized': 0,
            'total_km_saved': 0,
            'total_time_saved_minutes': 0,
            'total_fuel_saved_liters': 0,
            'average_improvement_percent': 0,
            'best_optimization': None
        }

# ==================== CREACIÓN DE LA APLICACIÓN ====================
def create_app():
    app = Flask(__name__)
    
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'clave_secreta_para_flask')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///app.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = './uploads'
    
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = 'Por favor inicia sesión para acceder a esta página'
    
   
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @app.context_processor
    def inject_global_data():
        """Inyectar datos globales a todos los templates"""
        return {
            'get_recent_completions': get_recent_completions
        }

    # Filtros de template
    @app.template_filter('datetime_format')
    def datetime_format(value, format='%d/%m/%Y %H:%M'):
        if value is None:
            return "Fecha no disponible"
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return value
        return value.strftime(format)

    @app.template_filter('distance_format')
    def distance_format(meters):
        if meters is None:
            return "N/A"
        if meters < 1000:
            return f"{int(meters)} m"
        else:
            return f"{meters/1000:.2f} km"

    @app.template_filter('fuel_level_display')
    def fuel_level_display(level):
        if level is None:
            return "N/A"
        return f"{level}/4"
    
    @app.template_filter('from_json')
    def from_json_filter(value):
        """Convertir string JSON a objeto Python"""
        try:
            import json
            if isinstance(value, str):
                return json.loads(value)
            return value
        except:
            return []

    @app.template_filter('format_distance_saved')
    def format_distance_saved(km_value):
        """Formatear kilómetros ahorrados"""
        if km_value is None or km_value == 0:
            return "Sin ahorro"
        return f"{km_value:.2f} km ahorrados"

    @app.template_filter('format_time_saved')
    def format_time_saved(minutes):
        """Formatear tiempo ahorrado"""
        if minutes is None or minutes == 0:
            return "Sin ahorro de tiempo"
        if minutes < 60:
            return f"~{minutes} min ahorrados"
        else:
            hours = minutes // 60
            remaining_minutes = minutes % 60
            return f"~{hours}h {remaining_minutes}m ahorrados"

    @app.template_filter('format_optimization_level')
    def format_optimization_level(level):
        """Formatear nivel de optimización"""
        if not level:
            return 'No especificado'
        
        levels = {
            'basic': 'Básica',
            'medium': 'Media', 
            'advanced': 'Avanzada',
            'none': 'Sin optimización'
        }
        return levels.get(level, level.capitalize())

    @app.template_filter('format_distance_saved')
    def format_distance_saved(km_value):
        """Formatear kilómetros ahorrados"""
        if km_value is None or km_value == 0:
            return "Sin ahorro"
        return f"{km_value:.2f} km ahorrados"

    @app.template_filter('format_time_saved')
    def format_time_saved(minutes):
        """Formatear tiempo ahorrado"""
        if minutes is None or minutes == 0:
            return "Sin ahorro de tiempo"
        if minutes < 60:
            return f"~{minutes} min ahorrados"
        else:
            hours = minutes // 60
            remaining_minutes = minutes % 60
            return f"~{hours}h {remaining_minutes}m ahorrados"




    # ==================== RUTAS PRINCIPALES ====================
    
    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        else:
            return redirect(url_for('login'))

    @app.route('/dashboard')
    @login_required
    def dashboard():
        if current_user.is_admin:
            return redirect(url_for('admin_dashboard'))
        elif current_user.is_technician:
            return redirect(url_for('technician_dashboard'))
        elif current_user.is_coordinator:
            return redirect(url_for('coordinator_dashboard'))
        else:
            return redirect(url_for('driver_dashboard'))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            
            user = User.query.filter_by(username=username, active=True).first()
            
            if user and user.check_password(password):
                login_user(user)
                flash('¡Inicio de sesión exitoso!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Usuario o contraseña incorrectos.', 'danger')
        
        return render_template('login.html', now=datetime.now())

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('Has cerrado sesión correctamente.', 'success')
        return redirect(url_for('login'))

    # ==================== RUTAS DE ADMINISTRADOR ====================
    
    @app.route('/admin/dashboard')
    @admin_required
    def admin_dashboard():
        total_users = User.query.filter_by(active=True).count()
        total_drivers = User.query.filter_by(role='driver', active=True).count()
        total_vehicles = Vehicle.query.filter_by(active=True).count()
        total_routes = Route.query.filter_by(active=True).count()
        recent_routes = Route.query.order_by(Route.created_at.desc()).limit(5).all()
        completed_routes = RouteCompletion.query.filter_by(status='completed').count()
        in_progress_routes = RouteCompletion.query.filter_by(status='in_progress').count()
        
        return render_template(
            'admin/dashboard.html',
            total_users=total_users,
            total_drivers=total_drivers,
            total_vehicles=total_vehicles, 
            total_routes=total_routes,
            recent_routes=recent_routes,
            completed_routes=completed_routes,
            in_progress_routes=in_progress_routes,
            get_optimized_routes_count=get_optimized_routes_count,
            get_optimization_summary=get_optimization_summary,
        )

    @app.route('/admin/users')
    @admin_required
    def manage_users():
        users = User.query.filter_by(active=True).order_by(User.role, User.last_name).all()
        return render_template('admin/users.html', users=users)

    @app.route('/admin/create_user', methods=['GET', 'POST'])
    @admin_required
    def create_user():
        if request.method == 'POST':
            username = request.form.get('username')
            email = request.form.get('email')
            password = request.form.get('password')
            first_name = request.form.get('first_name')
            last_name = request.form.get('last_name')
            cedula = request.form.get('cedula')
            role = request.form.get('role')
            license_type = request.form.get('license_type')
            
            if User.query.filter_by(username=username).first():
                flash('El nombre de usuario ya existe.', 'danger')
                return redirect(url_for('create_user'))
            
            if User.query.filter_by(email=email).first():
                flash('El email ya está registrado.', 'danger')
                return redirect(url_for('create_user'))
            
            if User.query.filter_by(cedula=cedula).first():
                flash('La cédula ya está registrada.', 'danger')
                return redirect(url_for('create_user'))
            
            new_user = User(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                cedula=cedula,
                role=role
            )
            new_user.set_password(password)
            
            db.session.add(new_user)
            db.session.flush()
            
            if role == 'driver' and license_type:
                driver_info = DriverInfo(
                    user_id=new_user.id,
                    license_type=license_type
                )
                db.session.add(driver_info)
            
            db.session.commit()
            flash(f'Usuario {role} creado exitosamente.', 'success')
            return redirect(url_for('manage_users'))
        
        return render_template('admin/create_user.html')

    @app.route('/admin/routes')
    @admin_required
    def manage_routes():
        routes = Route.query.filter_by(active=True).order_by(Route.created_at.desc()).all()
        return render_template('admin/routes.html', routes=routes)

    @app.route('/admin/create_route', methods=['GET', 'POST'])
    @admin_required
    def create_route():
        if request.method == 'POST':
            print("=== INICIANDO CREACIÓN DE RUTA CON MÉTRICAS ===")
            
            try:
                files = request.files.getlist('gpx_files')
                route_name = request.form.get('route_name')
                route_description = request.form.get('route_description')
                optimization_level = request.form.get('optimization_level', 'medium')
                
                print(f"Nombre de ruta: {route_name}")
                print(f"Descripción: {route_description}")
                print(f"Nivel de optimización: {optimization_level}")
                print(f"Archivos recibidos: {len(files)}")
                
                # Validaciones básicas
                if not route_name or not files:
                    flash('Nombre de ruta y archivos GPX son requeridos.', 'danger')
                    return redirect(url_for('create_route'))
                
                if Route.query.filter_by(name=route_name).first():
                    flash('Ya existe una ruta con ese nombre.', 'danger')
                    return redirect(url_for('create_route'))
                
                # Verificar que tenemos archivos válidos
                valid_files = [f for f in files if f.filename and f.filename.endswith('.gpx')]
                if not valid_files:
                    flash('No se subieron archivos GPX válidos.', 'danger')
                    return redirect(url_for('create_route'))
                
                print(f"Archivos GPX válidos: {len(valid_files)}")
                
                uploaded_files = []
                original_gpx_path = None
                
                # Guardar archivos GPX
                print("\n=== GUARDANDO ARCHIVOS GPX ===")
                for i, file in enumerate(valid_files):
                    print(f"Procesando archivo {i+1}: {file.filename}")
                    
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                    filename = secure_filename(f"{timestamp}_{file.filename}")
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    
                    # Guardar archivo
                    file.save(filepath)
                    print(f"Archivo guardado en: {filepath}")
                    
                    # Verificar que el archivo se guardó correctamente
                    if os.path.exists(filepath):
                        file_size = os.path.getsize(filepath)
                        print(f"Tamaño del archivo: {file_size} bytes")
                        
                        uploaded_files.append(filepath)
                        
                        if not original_gpx_path:
                            original_gpx_path = filepath
                    else:
                        print(f"ERROR: No se pudo guardar el archivo {filepath}")
                
                if not uploaded_files:
                    flash('Error al guardar los archivos GPX.', 'danger')
                    return redirect(url_for('create_route'))
                
                print(f"Archivos guardados exitosamente: {len(uploaded_files)}")
                
                # Usar optimizador avanzado
                print("\n=== INICIALIZANDO OPTIMIZADOR ===")
                optimizer = AdvancedRouteOptimizer()
                
                print(f"Iniciando optimización de ruta '{route_name}' con nivel: {optimization_level}")
                
                # Cargar puntos originales para comparación
                print("\n=== CARGANDO PUNTOS ORIGINALES ===")
                original_points = []
                for file_path in uploaded_files:
                    try:
                        points = optimizer.load_gpx_points(file_path)
                        original_points.extend(points)
                        print(f"Puntos cargados de {file_path}: {len(points)}")
                    except Exception as e:
                        print(f"Error cargando {file_path}: {e}")
                        continue
                
                if not original_points:
                    flash('No se pudieron cargar puntos de los archivos GPX.', 'danger')
                    return redirect(url_for('create_route'))
                
                print(f"Total de puntos originales cargados: {len(original_points)}")
                
                # Calcular distancia original
                original_distance = optimizer.calculate_total_distance(original_points)
                print(f"Distancia original: {original_distance} metros")
                
                # Optimizar ruta
                print("\n=== OPTIMIZANDO RUTA ===")
                try:
                    # Intentar optimización normal primero
                    optimal_path, optimized_distance = optimizer.optimize_route_advanced(
                        uploaded_files, 
                        optimize_level=optimization_level
                    )
                    optimization_success = True
                except Exception as e:
                    print(f"Error en optimización avanzada: {e}")
                    print("Intentando optimización rápida...")
                    try:
                        # Usar optimización rápida como respaldo
                        optimal_path, optimized_distance = optimizer.optimize_route_quick(
                            uploaded_files, 
                            optimize_level='basic'
                        )
                        optimization_level = 'basic'  # Actualizar el nivel usado
                        optimization_success = True
                    except Exception as e2:
                        print(f"Error en optimización rápida: {e2}")
                        # Como último recurso, usar solo los puntos originales
                        optimal_path = original_points
                        optimized_distance = original_distance
                        optimization_level = 'none'
                        optimization_success = False
                        print("Usando puntos originales sin optimización")
                
                print(f"Optimización completada:")
                print(f"  - Puntos finales: {len(optimal_path)}")
                print(f"  - Distancia final: {optimized_distance} metros")
                
                # Calcular métricas de optimización
                print("\n=== CALCULANDO MÉTRICAS DE OPTIMIZACIÓN ===")
                
                # Calcular ahorro de distancia
                distance_saved_meters = max(0, original_distance - optimized_distance)
                distance_saved_km = distance_saved_meters / 1000
                distance_saved_percent = (distance_saved_meters / original_distance * 100) if original_distance > 0 else 0
                
                # Calcular tiempo ahorrado (asumiendo velocidad promedio de 40 km/h)
                average_speed_kmh = 40
                time_saved_hours = distance_saved_km / average_speed_kmh
                time_saved_minutes = int(time_saved_hours * 60)
                
                # Detectar bucles eliminados
                original_loops = optimizer.detect_loops(original_points)
                optimized_loops = optimizer.detect_loops(optimal_path)
                loops_removed = max(0, len(original_loops) - len(optimized_loops))
                
                # Calcular puntos reducidos
                points_reduced = max(0, len(original_points) - len(optimal_path))
                
                print(f"Métricas calculadas:")
                print(f"  - Distancia ahorrada: {distance_saved_km:.2f} km ({distance_saved_percent:.1f}%)")
                print(f"  - Tiempo ahorrado estimado: {time_saved_minutes} minutos")
                print(f"  - Bucles eliminados: {loops_removed}")
                print(f"  - Puntos reducidos: {points_reduced}")
                
                # Crear mapa optimizado
                print("\n=== CREANDO MAPA ===")
                route_map = optimizer.create_optimized_map(optimal_path, route_name)

                # Generar nombre de archivo ÚNICO y VERIFICADO
                max_attempts = 5
                map_filepath = None
                map_filename = None

                for attempt in range(max_attempts):
                    try:
                        # Generar nombre único con timestamp + UUID
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                        unique_id = uuid.uuid4().hex[:8]
                        map_filename = f"route_{route_name.replace(' ', '_')}_{timestamp}_{unique_id}.html"
                        
                        # Limpiar caracteres especiales del nombre
                        map_filename = "".join(c for c in map_filename if c.isalnum() or c in '._-')
                        
                        # Generar ruta completa
                        map_filepath = os.path.join('static', 'routes', map_filename)
                        
                        # Verificar que el directorio existe
                        os.makedirs(os.path.dirname(map_filepath), exist_ok=True)
                        
                        # Verificar que el archivo no existe ya
                        if not os.path.exists(map_filepath):
                            break
                        else:
                            print(f"Archivo ya existe, intentando otro nombre (intento {attempt + 1})")
                            map_filepath = None
                            
                    except Exception as e:
                        print(f"Error generando nombre de archivo (intento {attempt + 1}): {e}")
                        map_filepath = None

                if not map_filepath:
                    raise Exception("No se pudo generar un nombre de archivo único después de varios intentos")

                print(f"Nombre de archivo generado: {map_filename}")
                print(f"Ruta completa: {map_filepath}")

                # Guardar mapa con verificaciones
                try:
                    print("Guardando mapa...")
                    route_map.save(map_filepath)
                    
                    # VERIFICAR QUE EL ARCHIVO SE GUARDÓ CORRECTAMENTE
                    if not os.path.exists(map_filepath):
                        raise Exception(f"El archivo no se creó: {map_filepath}")
                    
                    file_size = os.path.getsize(map_filepath)
                    if file_size < 1000:  # Archivo muy pequeño, probablemente corrupto
                        raise Exception(f"Archivo demasiado pequeño ({file_size} bytes), posiblemente corrupto")
                    
                    print(f"Mapa guardado exitosamente:")
                    print(f"  - Archivo: {map_filepath}")
                    print(f"  - Tamaño: {file_size} bytes")
                    
                    # VERIFICAR CONTENIDO DEL ARCHIVO
                    with open(map_filepath, 'r', encoding='utf-8') as f:
                        content_preview = f.read(100)
                        if '<html' not in content_preview.lower():
                            print("ADVERTENCIA: El archivo no parece ser HTML válido")
                        else:
                            print("  - Contenido: HTML válido detectado")
                    
                except Exception as e:
                    print(f"ERROR guardando mapa: {e}")
                    
                    # Intentar crear un mapa básico de respaldo
                    try:
                        print("Creando mapa básico de respaldo...")
                        basic_map_content = create_basic_fallback_map_html(optimal_path, route_name)
                        
                        with open(map_filepath, 'w', encoding='utf-8') as f:
                            f.write(basic_map_content)
                        
                        print(f"Mapa básico creado como respaldo")
                        
                    except Exception as e2:
                        print(f"ERROR creando mapa básico: {e2}")
                        raise Exception(f"No se pudo crear el mapa: {e}. Respaldo falló: {e2}")

                # Crear nueva ruta en base de datos con VERIFICACIONES
                print("\n=== GUARDANDO EN BASE DE DATOS ===")

                # VERIFICAR UNA VEZ MÁS que los archivos existen antes de guardar en BD
                if not os.path.exists(map_filepath):
                    raise Exception(f"CRÍTICO: Archivo de mapa desapareció antes de guardar en BD: {map_filepath}")

                if original_gpx_path and not os.path.exists(original_gpx_path):
                    print(f"ADVERTENCIA: Archivo GPX no existe: {original_gpx_path}")
                    original_gpx_path = None

                new_route = Route(
                    name=route_name,
                    description=route_description,
                    creator_id=current_user.id,
                    file_path=map_filepath,  # Ruta VERIFICADA
                    gpx_path=original_gpx_path,  # Puede ser None si no existe
                    start_point=f"{optimal_path[0][0]},{optimal_path[0][1]}",
                    end_point=f"{optimal_path[-1][0]},{optimal_path[-1][1]}",
                    distance=optimized_distance,
                    # Métricas de optimización
                    original_distance=original_distance,
                    distance_saved_km=distance_saved_km,
                    distance_saved_percent=distance_saved_percent,
                    estimated_time_saved_minutes=time_saved_minutes,
                    optimization_level=optimization_level,
                    loops_removed=loops_removed,
                    points_reduced=points_reduced
                )

                try:
                    db.session.add(new_route)
                    db.session.commit()
                    
                    print(f"Ruta guardada en BD con ID: {new_route.id}")
                    
                    # VERIFICACIÓN FINAL POST-COMMIT
                    final_check = os.path.exists(map_filepath)
                    print(f"Verificación final - archivo existe: {final_check}")
                    
                    if not final_check:
                        print("ALERTA: El archivo desapareció después del commit!")
                    
                except Exception as e:
                    print(f"ERROR guardando en BD: {e}")
                    db.session.rollback()
                    
                    # Limpiar archivo si falló la BD
                    if os.path.exists(map_filepath):
                        try:
                            os.remove(map_filepath)
                            print(f"Archivo limpiado después de error en BD")
                        except:
                            pass
                    
                    raise

                # Mensaje de éxito con métricas detalladas
                if optimization_success and distance_saved_km > 0:
                    success_message = f'''Ruta "{route_name}" creada y optimizada exitosamente! 
                                        ✅ {distance_saved_km:.2f} km ahorrados ({distance_saved_percent:.1f}% de mejora)
                                        ⏱️ ~{time_saved_minutes} minutos de tiempo estimado ahorrado
                                        🔄 {loops_removed} bucles eliminados
                                        📊 {points_reduced} puntos de ruta optimizados'''
                else:
                    success_message = f'Ruta "{route_name}" creada correctamente (sin optimización aplicada).'
                
                print("=== RUTA CREADA EXITOSAMENTE ===")
                flash(success_message, 'success')
                return redirect(url_for('manage_routes'))
                
            except Exception as e:
                print(f"\n=== ERROR EN CREACIÓN DE RUTA ===")
                print(f"Error: {str(e)}")
                import traceback
                print(f"Traceback completo:")
                traceback.print_exc()
                
                flash(f'Error al procesar la ruta: {str(e)}', 'danger')
                return redirect(url_for('create_route'))
        
        return render_template('admin/create_route.html')

    @app.route('/admin/vehicles')
    @admin_required
    def manage_vehicles():
        vehicles = Vehicle.query.filter_by(active=True).order_by(Vehicle.brand).all()
        return render_template('admin/vehicles.html', vehicles=vehicles)

    @app.route('/admin/add_vehicle', methods=['GET', 'POST'])
    @admin_required
    def add_vehicle():
        if request.method == 'POST':
            brand = request.form.get('brand')
            model = request.form.get('model')
            year = request.form.get('year')
            plate_number = request.form.get('plate_number')
            
            if Vehicle.query.filter_by(plate_number=plate_number).first():
                flash('Ya existe un vehículo con esa placa.', 'danger')
                return redirect(url_for('add_vehicle'))
            
            new_vehicle = Vehicle(
                brand=brand,
                model=model,
                year=year,
                plate_number=plate_number
            )
            
            db.session.add(new_vehicle)
            db.session.commit()
            
            flash('Vehículo añadido correctamente.', 'success')
            return redirect(url_for('manage_vehicles'))
        
        return render_template('admin/add_vehicle.html')

    @app.route('/admin/edit_vehicle/<int:vehicle_id>', methods=['GET', 'POST'])
    @admin_required
    def edit_vehicle(vehicle_id):
        try:
            vehicle = Vehicle.query.get_or_404(vehicle_id)
            
            if request.method == 'POST':
                vehicle.brand = request.form.get('brand')
                vehicle.model = request.form.get('model')
                vehicle.year = request.form.get('year')
                plate_number = request.form.get('plate_number')
                
                existing_vehicle = Vehicle.query.filter(
                    Vehicle.plate_number == plate_number,
                    Vehicle.id != vehicle.id
                ).first()
                
                if existing_vehicle:
                    flash('Ya existe un vehículo con esa placa.', 'danger')
                    return redirect(url_for('edit_vehicle', vehicle_id=vehicle_id))
                
                vehicle.plate_number = plate_number
                db.session.commit()
                
                flash('Vehículo actualizado correctamente.', 'success')
                return redirect(url_for('manage_vehicles'))
            
            return render_template('admin/edit_vehicle.html', vehicle=vehicle)
            
        except Exception as e:
            print(f"ERROR en edit_vehicle: {e}")
            flash(f'Error al editar el vehículo: {str(e)}', 'danger')
            return redirect(url_for('manage_vehicles'))

    @app.route('/admin/view_route/<int:route_id>')
    @admin_required
    def admin_view_route(route_id):
        route = Route.query.get_or_404(route_id)
        
        try:
            with open(route.file_path, 'r', encoding='utf-8') as f:
                map_html = f.read()
        except Exception as e:
            map_html = "<p>No se pudo cargar el mapa</p>"
        
        completions = RouteCompletion.query.filter_by(route_id=route.id).order_by(RouteCompletion.completed_at.desc()).all()
        
        return render_template('admin/view_route.html',
                             route=route,
                             map_html=map_html,
                             completions=completions)

    @app.route('/admin/delete_route/<int:route_id>', methods=['POST'])
    @admin_required
    def delete_route(route_id):
        route = Route.query.get_or_404(route_id)
        
        RouteCompletion.query.filter_by(route_id=route_id).delete()
        
        if route.file_path and os.path.exists(route.file_path):
            try:
                os.remove(route.file_path)
            except:
                pass
        
        if route.gpx_path and os.path.exists(route.gpx_path):
            try:
                os.remove(route.gpx_path)
            except:
                pass
        
        db.session.delete(route)
        db.session.commit()
        
        flash('Ruta eliminada correctamente.', 'success')
        return redirect(url_for('manage_routes'))



    @app.route('/admin/repair_broken_routes')
    @admin_required
    def repair_broken_routes():
        """Reparar rutas con archivos de mapa faltantes"""
        try:
            print("=== INICIANDO REPARACIÓN DE RUTAS ===")
            
            # Obtener todas las rutas activas
            routes = Route.query.filter_by(active=True).all()
            
            repaired_count = 0
            error_count = 0
            
            for route in routes:
                try:
                    print(f"\nProcesando ruta: {route.name} (ID: {route.id})")
                    
                    # Verificar si el archivo del mapa existe
                    map_file_missing = not route.file_path or not os.path.exists(route.file_path)
                    
                    if map_file_missing:
                        print(f"  - Archivo de mapa faltante: {route.file_path}")
                        
                        # Intentar reparar desde GPX
                        if route.gpx_path and os.path.exists(route.gpx_path):
                            print(f"  - Intentando reparar desde GPX: {route.gpx_path}")
                            
                            # Cargar puntos del GPX
                            optimizer = AdvancedRouteOptimizer()
                            points = optimizer.load_gpx_points(route.gpx_path)
                            
                            if points:
                                # Crear nuevo mapa
                                route_map = optimizer.create_optimized_map(points, route.name)
                                
                                # Generar nuevo nombre de archivo
                                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                                new_filename = f"route_{route.id}_{timestamp}.html"
                                new_filepath = os.path.join('static', 'routes', new_filename)
                                
                                # Asegurar que el directorio existe
                                os.makedirs(os.path.dirname(new_filepath), exist_ok=True)
                                
                                # Guardar mapa
                                route_map.save(new_filepath)
                                
                                # Actualizar base de datos
                                route.file_path = new_filepath
                                
                                print(f"  ✓ Mapa reparado: {new_filepath}")
                                repaired_count += 1
                                
                            else:
                                print(f"  ✗ No se pudieron cargar puntos del GPX")
                                error_count += 1
                        else:
                            print(f"  ✗ No hay archivo GPX disponible: {route.gpx_path}")
                            error_count += 1
                    else:
                        print(f"  ✓ Mapa OK: {route.file_path}")
                        
                except Exception as e:
                    print(f"  ✗ Error procesando ruta {route.id}: {e}")
                    error_count += 1
                    continue
            
            # Commit cambios
            db.session.commit()
            
            flash(f'Reparación completada: {repaired_count} rutas reparadas, {error_count} errores', 'success')
            
            print(f"\n=== REPARACIÓN COMPLETADA ===")
            print(f"Rutas reparadas: {repaired_count}")
            print(f"Errores: {error_count}")
            
            return redirect(url_for('admin_dashboard'))
            
        except Exception as e:
            print(f"Error en reparación: {e}")
            flash(f'Error durante la reparación: {str(e)}', 'danger')
            return redirect(url_for('admin_dashboard'))


    @app.route('/admin/clean_broken_files')
    @admin_required  
    def clean_broken_files():
        """Limpiar referencias a archivos que no existen"""
        try:
            print("=== LIMPIANDO REFERENCIAS ROTAS ===")
            
            routes = Route.query.filter_by(active=True).all()
            cleaned_count = 0
            
            for route in routes:
                updated = False
                
                # Limpiar file_path si no existe
                if route.file_path and not os.path.exists(route.file_path):
                    print(f"Limpiando file_path roto: {route.file_path}")
                    route.file_path = None
                    updated = True
                
                # Limpiar gpx_path si no existe  
                if route.gpx_path and not os.path.exists(route.gpx_path):
                    print(f"Limpiando gpx_path roto: {route.gpx_path}")
                    route.gpx_path = None
                    updated = True
                
                if updated:
                    cleaned_count += 1
            
            db.session.commit()
            
            flash(f'Limpieza completada: {cleaned_count} rutas actualizadas', 'success')
            return redirect(url_for('admin_dashboard'))
            
        except Exception as e:
            flash(f'Error en limpieza: {str(e)}', 'danger')
            return redirect(url_for('admin_dashboard'))




    @app.route('/admin/ensure_directories')
    @admin_required
    def ensure_directories():
        """Crear directorios necesarios si no existen"""
        try:
            directories = [
                'static/routes',
                'static/completions',
                'uploads',
                'temp'
            ]
            
            created_dirs = []
            existing_dirs = []
            
            for directory in directories:
                abs_path = os.path.abspath(directory)
                
                if os.path.exists(abs_path):
                    existing_dirs.append(directory)
                else:
                    os.makedirs(abs_path, exist_ok=True)
                    created_dirs.append(directory)
            
            # Verificar permisos de escritura
            permission_issues = []
            for directory in directories:
                abs_path = os.path.abspath(directory)
                if not os.access(abs_path, os.W_OK):
                    permission_issues.append(directory)
            
            if permission_issues:
                flash(f'Directorios sin permisos de escritura: {", ".join(permission_issues)}', 'warning')
            
            if created_dirs:
                flash(f'Directorios creados: {", ".join(created_dirs)}', 'success')
            
            if not created_dirs and not permission_issues:
                flash('Todos los directorios ya existen y tienen permisos correctos', 'info')
            
            return redirect(url_for('admin_dashboard'))
            
        except Exception as e:
            flash(f'Error creando directorios: {str(e)}', 'danger')
            return redirect(url_for('admin_dashboard'))

    @app.route('/admin/diagnose_system')
    @admin_required
    def diagnose_system():
        """Diagnóstico completo del sistema de rutas"""
        try:
            diagnosis = {
                'timestamp': datetime.now().isoformat(),
                'directories': {},
                'routes': {},
                'files': {},
                'database': {},
                'permissions': {},
                'recommendations': []
            }
            
            print("=== INICIANDO DIAGNÓSTICO COMPLETO ===")
            
            # 1. VERIFICAR DIRECTORIOS
            print("1. Verificando directorios...")
            directories = ['static', 'static/routes', 'static/completions', 'uploads', 'temp']
            
            for directory in directories:
                abs_path = os.path.abspath(directory)
                diagnosis['directories'][directory] = {
                    'exists': os.path.exists(abs_path),
                    'writable': os.access(abs_path, os.W_OK) if os.path.exists(abs_path) else False,
                    'absolute_path': abs_path
                }
                
                if not os.path.exists(abs_path):
                    diagnosis['recommendations'].append(f"Crear directorio faltante: {directory}")
                elif not os.access(abs_path, os.W_OK):
                    diagnosis['recommendations'].append(f"Corregir permisos de escritura en: {directory}")
            
            # 2. VERIFICAR BASE DE DATOS
            print("2. Verificando base de datos...")
            total_routes = Route.query.count()
            active_routes = Route.query.filter_by(active=True).count()
            routes_with_files = Route.query.filter(Route.file_path.isnot(None)).count()
            routes_with_gpx = Route.query.filter(Route.gpx_path.isnot(None)).count()
            
            diagnosis['database'] = {
                'total_routes': total_routes,
                'active_routes': active_routes,
                'routes_with_file_path': routes_with_files,
                'routes_with_gpx_path': routes_with_gpx
            }
            
            # 3. VERIFICAR ARCHIVOS DE RUTAS
            print("3. Verificando archivos de rutas...")
            routes = Route.query.filter_by(active=True).all()
            
            file_issues = []
            valid_files = 0
            missing_files = 0
            corrupted_files = 0
            
            for route in routes:
                route_status = {
                    'id': route.id,
                    'name': route.name,
                    'file_path': route.file_path,
                    'gpx_path': route.gpx_path,
                    'file_exists': False,
                    'file_valid': False,
                    'gpx_exists': False,
                    'issues': []
                }
                
                # Verificar file_path
                if route.file_path:
                    if os.path.exists(route.file_path):
                        route_status['file_exists'] = True
                        
                        try:
                            # Verificar contenido del archivo
                            with open(route.file_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                                
                            if len(content) > 500 and '<html' in content.lower():
                                route_status['file_valid'] = True
                                valid_files += 1
                            else:
                                route_status['issues'].append('Archivo HTML inválido o vacío')
                                corrupted_files += 1
                                
                        except Exception as e:
                            route_status['issues'].append(f'Error leyendo archivo: {e}')
                            corrupted_files += 1
                    else:
                        route_status['issues'].append('Archivo de mapa no existe')
                        missing_files += 1
                else:
                    route_status['issues'].append('Sin file_path definido')
                
                # Verificar gpx_path
                if route.gpx_path:
                    route_status['gpx_exists'] = os.path.exists(route.gpx_path)
                    if not route_status['gpx_exists']:
                        route_status['issues'].append('Archivo GPX no existe')
                
                if route_status['issues']:
                    file_issues.append(route_status)
            
            diagnosis['files'] = {
                'total_checked': len(routes),
                'valid_files': valid_files,
                'missing_files': missing_files,
                'corrupted_files': corrupted_files,
                'issues': file_issues
            }
            
            # 4. VERIFICAR PERMISOS
            print("4. Verificando permisos...")
            test_paths = ['static/routes', 'uploads']
            
            for path in test_paths:
                try:
                    test_file = os.path.join(path, 'test_write.tmp')
                    with open(test_file, 'w') as f:
                        f.write('test')
                    os.remove(test_file)
                    diagnosis['permissions'][path] = 'OK'
                except Exception as e:
                    diagnosis['permissions'][path] = f'ERROR: {e}'
                    diagnosis['recommendations'].append(f"Corregir permisos de escritura en {path}")
            
            # 5. VERIFICAR SERVICIOS
            print("5. Verificando servicios...")
            services_status = {}
            
            try:
                optimizer = AdvancedRouteOptimizer()
                services_status['route_optimizer'] = 'OK'
            except Exception as e:
                services_status['route_optimizer'] = f'ERROR: {e}'
                diagnosis['recommendations'].append("Revisar importación de AdvancedRouteOptimizer")
            
            try:
                import folium
                services_status['folium'] = 'OK'
            except Exception as e:
                services_status['folium'] = f'ERROR: {e}'
                diagnosis['recommendations'].append("Instalar o reparar biblioteca Folium")
            
            diagnosis['services'] = services_status
            
            # 6. GENERAR RECOMENDACIONES FINALES
            if missing_files > 0:
                diagnosis['recommendations'].append(f"Ejecutar reparación de {missing_files} rutas con archivos faltantes")
            
            if corrupted_files > 0:
                diagnosis['recommendations'].append(f"Regenerar {corrupted_files} archivos corruptos")
            
            if len(diagnosis['recommendations']) == 0:
                diagnosis['recommendations'].append("Sistema en estado saludable - no se requieren acciones")
            
            print("=== DIAGNÓSTICO COMPLETADO ===")
            
            return jsonify(diagnosis)
            
        except Exception as e:
            print(f"Error en diagnóstico: {e}")
            return jsonify({'error': str(e)})

    @app.route('/admin/fix_all_issues')
    @admin_required
    def fix_all_issues():
        """Intentar reparar automáticamente todos los problemas detectados"""
        try:
            print("=== INICIANDO REPARACIÓN AUTOMÁTICA ===")
            
            results = {
                'directories_created': [],
                'routes_repaired': [],
                'files_cleaned': [],
                'errors': []
            }
            
            # 1. Crear directorios faltantes
            directories = ['static/routes', 'static/completions', 'uploads', 'temp']
            for directory in directories:
                try:
                    if not os.path.exists(directory):
                        os.makedirs(directory, exist_ok=True)
                        results['directories_created'].append(directory)
                except Exception as e:
                    results['errors'].append(f"Error creando {directory}: {e}")
            
            # 2. Reparar rutas con archivos faltantes
            routes = Route.query.filter_by(active=True).all()
            
            for route in routes:
                try:
                    needs_repair = False
                    
                    # Verificar si necesita reparación
                    if not route.file_path or not os.path.exists(route.file_path):
                        needs_repair = True
                    
                    if needs_repair and route.gpx_path and os.path.exists(route.gpx_path):
                        # Intentar reparar
                        optimizer = AdvancedRouteOptimizer()
                        points = optimizer.load_gpx_points(route.gpx_path)
                        
                        if points:
                            # Crear nuevo mapa
                            route_map = optimizer.create_optimized_map(points, route.name)
                            
                            # Generar nuevo archivo
                            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                            filename = f"route_{route.id}_repaired_{timestamp}.html"
                            filepath = os.path.join('static', 'routes', filename)
                            
                            route_map.save(filepath)
                            
                            # Actualizar BD
                            route.file_path = filepath
                            
                            results['routes_repaired'].append({
                                'id': route.id,
                                'name': route.name,
                                'new_file': filepath
                            })
                            
                except Exception as e:
                    results['errors'].append(f"Error reparando ruta {route.id}: {e}")
            
            # 3. Commit cambios
            try:
                db.session.commit()
            except Exception as e:
                results['errors'].append(f"Error guardando cambios: {e}")
                db.session.rollback()
            
            # Generar mensaje de resultado
            success_count = len(results['directories_created']) + len(results['routes_repaired']) + len(results['files_cleaned'])
            error_count = len(results['errors'])
            
            if success_count > 0 and error_count == 0:
                flash(f'Reparación completada exitosamente: {success_count} elementos reparados', 'success')
            elif success_count > 0 and error_count > 0:
                flash(f'Reparación parcial: {success_count} reparados, {error_count} errores', 'warning')
            elif error_count > 0:
                flash(f'Reparación falló: {error_count} errores encontrados', 'danger')
            else:
                flash('No se encontraron problemas para reparar', 'info')
            
            print("=== REPARACIÓN AUTOMÁTICA COMPLETADA ===")
            
            return jsonify(results)
            
        except Exception as e:
            flash(f'Error en reparación automática: {str(e)}', 'danger')
            return jsonify({'error': str(e)})


    # ==================== RUTAS DE TÉCNICO ====================
    
    @app.route('/technician/dashboard')
    @technician_required
    def technician_dashboard():
        users = User.query.filter_by(active=True).order_by(User.role, User.last_name).all()
        return render_template('technician/dashboard.html', users=users)

    @app.route('/technician/change_password/<int:user_id>', methods=['GET', 'POST'])
    @technician_required
    def change_user_password(user_id):
        user = User.query.get_or_404(user_id)
            
        if request.method == 'POST':
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
                
            if new_password != confirm_password:
                flash('Las contraseñas no coinciden.', 'danger')
                return redirect(url_for('change_user_password', user_id=user_id))
                
            user.set_password(new_password)
            db.session.commit()
                
            flash(f'Contraseña de {user.username} actualizada correctamente.', 'success')
            return redirect(url_for('technician_dashboard'))
            
        return render_template('technician/change_password.html', user=user)

    # ==================== RUTAS DE COORDINADOR ====================
    
    @app.route('/coordinator/dashboard')
    @coordinator_required
    def coordinator_dashboard():
        total_routes = Route.query.filter_by(active=True).count()
        completed_routes = RouteCompletion.query.filter_by(status='completed').count()
        in_progress_routes = RouteCompletion.query.filter_by(status='in_progress').count()
        total_drivers = User.query.filter_by(role='driver', active=True).count()
        
        recent_completions = RouteCompletion.query.order_by(RouteCompletion.completed_at.desc()).limit(10).all()
        
        return render_template('coordinator/dashboard.html',
                             total_routes=total_routes,
                             completed_routes=completed_routes,
                             in_progress_routes=in_progress_routes,
                             total_drivers=total_drivers,
                             recent_completions=recent_completions)

    @app.route('/coordinator/routes')
    @coordinator_required
    def coordinator_view_routes():
        routes = Route.query.filter_by(active=True).order_by(Route.created_at.desc()).all()
        return render_template('coordinator/routes.html', routes=routes)

    @app.route('/coordinator/view_route/<int:route_id>')
    @coordinator_required
    def coordinator_view_route(route_id):
        route = Route.query.get_or_404(route_id)
        
        try:
            with open(route.file_path, 'r', encoding='utf-8') as f:
                map_html = f.read()
        except Exception as e:
            map_html = "<p>No se pudo cargar el mapa</p>"
        
        completions = RouteCompletion.query.filter_by(route_id=route.id).order_by(RouteCompletion.completed_at.desc()).all()
        
        return render_template('coordinator/view_route.html',
                             route=route,
                             map_html=map_html,
                             completions=completions)
    # ==================== RUTAS DE CHOFER (CORREGIDAS) ====================
    
    @app.route('/driver/dashboard')
    @driver_required
    def driver_dashboard():
        driver_info = DriverInfo.query.filter_by(user_id=current_user.id).first()
        
        if driver_info:
            active_assignment = VehicleAssignment.query.filter_by(
                driver_id=driver_info.id, active=True
            ).first()
            vehicle = active_assignment.vehicle if active_assignment else None
        else:
            vehicle = None
        
        available_vehicles = Vehicle.query.filter_by(active=True).all()
        available_routes = Route.query.filter_by(active=True).order_by(Route.created_at.desc()).all()
        recent_completions = RouteCompletion.query.filter_by(
            driver_id=current_user.id
        ).order_by(RouteCompletion.completed_at.desc()).limit(5).all()
        
        in_progress = RouteCompletion.query.filter_by(
            driver_id=current_user.id, 
            status='in_progress'
        ).first()
        
        return render_template('driver/dashboard.html',
                             driver_info=driver_info,
                             vehicle=vehicle,
                             available_vehicles=available_vehicles,
                             available_routes=available_routes,
                             recent_completions=recent_completions,
                             in_progress=in_progress)



    @app.route('/driver/route_history')
    @driver_required
    def driver_route_history():
        try:
            completions = RouteCompletion.query.filter_by(
                driver_id=current_user.id
            ).order_by(RouteCompletion.completed_at.desc()).all()
            
            return render_template('driver/route_history.html', completions=completions)
        except Exception as e:
            print(f"ERROR en driver_route_history: {e}")
            flash(f'Error al cargar el historial: {str(e)}', 'danger')
            return redirect(url_for('driver_dashboard'))



    @app.route('/driver/view_route/<int:route_id>')
    @driver_required
    def driver_view_route(route_id):
        try:
            route = Route.query.get_or_404(route_id)
            
            try:
                with open(route.file_path, 'r', encoding='utf-8') as f:
                    map_html = f.read()
            except Exception as e:
                print(f"Error cargando mapa: {e}")
                map_html = "<p>No se pudo cargar el mapa de la ruta</p>"
            
            # Verificar si el chofer tiene alguna ruta en progreso
            in_progress = RouteCompletion.query.filter_by(
                driver_id=current_user.id, 
                status='in_progress'
            ).first()
            
            # Verificar si esta ruta específica está en progreso
            this_route_in_progress = RouteCompletion.query.filter_by(
                driver_id=current_user.id,
                route_id=route_id,
                status='in_progress'
            ).first()

            available_vehicles = Vehicle.query.filter_by(active=True).all()

            return render_template('driver/view_route.html',
                                 route=route,
                                 map_html=map_html,
                                 in_progress=in_progress,
                                 this_route_in_progress=this_route_in_progress,
                                 available_vehicles=available_vehicles)
        except Exception as e:
            print(f"ERROR en driver_view_route: {e}")
            flash(f'Error al cargar la ruta: {str(e)}', 'danger')
            return redirect(url_for('driver_dashboard'))


    @app.route('/driver/start_route/<int:route_id>', methods=['POST'])
    @driver_required
    def driver_start_route(route_id):
        try:
            # Verificar si ya hay una ruta en progreso
            existing_route = RouteCompletion.query.filter_by(
                driver_id=current_user.id, 
                status='in_progress'
            ).first()
            
            if existing_route:
                return jsonify({
                    'success': False, 
                    'message': f'Ya tienes una ruta en progreso: {existing_route.route.name}. Debes completarla o cancelarla antes de iniciar otra.'
                }), 400
            
            route = Route.query.get_or_404(route_id)
            
            # Obtener datos del request
            data = request.get_json() if request.is_json else {}
            vehicle_id = data.get('vehicle_id')
            fuel_level = data.get('fuel_level')
            
            # Validaciones
            if not vehicle_id:
                return jsonify({'success': False, 'message': 'Debes seleccionar un vehículo'}), 400
            
            if not fuel_level or fuel_level not in [1, 2, 3, 4]:
                return jsonify({'success': False, 'message': 'Debes seleccionar el nivel de combustible (1-4)'}), 400
            
            vehicle = Vehicle.query.get(vehicle_id)
            if not vehicle or not vehicle.active:
                return jsonify({'success': False, 'message': 'El vehículo seleccionado no está disponible'}), 400
            
            # Crear nueva ruta en progreso
            new_completion = RouteCompletion(
                route_id=route.id,
                driver_id=current_user.id,
                vehicle_id=vehicle.id,
                started_at=datetime.utcnow(),
                status='in_progress',
                fuel_start=fuel_level
            )
            
            db.session.add(new_completion)
            db.session.commit()
            
            return jsonify({
                'success': True, 
                'message': f'Ruta "{route.name}" iniciada correctamente con {vehicle.brand} {vehicle.model} (combustible {fuel_level}/4)',
                'completion_id': new_completion.id,
                'navigate_url': url_for('driver_navigate', route_id=route.id)
            })
            
        except Exception as e:
            print(f"ERROR en driver_start_route: {e}")
            db.session.rollback()  # Importante: hacer rollback en caso de error
            return jsonify({'success': False, 'message': f'Error al iniciar la ruta: {str(e)}'}), 500




    # ==================== FUNCIÓN DRIVER_NAVIGATE CORREGIDA ====================

    @app.route('/driver/navigate/<int:route_id>')
    @driver_required
    def driver_navigate(route_id):
        try:
            route = Route.query.get_or_404(route_id)
            
            # Buscar la ruta en progreso del chofer
            in_progress = RouteCompletion.query.filter_by(
                driver_id=current_user.id,
                status='in_progress'
            ).first()
            
            if not in_progress:
                flash('Debes iniciar la ruta antes de navegar.', 'warning')
                return redirect(url_for('driver_view_route', route_id=route_id))
            
            # Verificar que la ruta en progreso sea la misma que se quiere navegar
            if in_progress.route_id != route_id:
                flash(f'Tienes otra ruta en progreso: {in_progress.route.name}. Complétala primero.', 'warning')
                return redirect(url_for('driver_dashboard'))
            
            print(f"\n=== CARGANDO MAPA PARA NAVEGACIÓN ===")
            print(f"Ruta: {route.name} (ID: {route.id})")
            print(f"file_path: {route.file_path}")
            print(f"gpx_path: {route.gpx_path}")
            
            map_html = None
            map_source = "none"
            
            # INTENTO 1: Cargar desde file_path
            if route.file_path:
                print(f"Intento 1: Cargando desde file_path: {route.file_path}")
                
                if os.path.exists(route.file_path):
                    try:
                        with open(route.file_path, 'r', encoding='utf-8') as f:
                            map_html = f.read()
                        
                        # Verificar que el contenido sea válido
                        if len(map_html) > 500 and '<html' in map_html.lower():
                            map_source = "file_path"
                            print(f"✓ Mapa cargado desde file_path ({len(map_html)} caracteres)")
                        else:
                            print(f"✗ Archivo existe pero contenido inválido (tamaño: {len(map_html)})")
                            map_html = None
                            
                    except Exception as e:
                        print(f"✗ Error leyendo file_path: {e}")
                        map_html = None
                else:
                    print(f"✗ file_path no existe: {route.file_path}")
            
            # INTENTO 2: Regenerar desde GPX
            if not map_html and route.gpx_path:
                print(f"Intento 2: Regenerando desde GPX: {route.gpx_path}")
                
                if os.path.exists(route.gpx_path):
                    try:
                        # Cargar puntos del GPX
                        optimizer = AdvancedRouteOptimizer()
                        points = optimizer.load_gpx_points(route.gpx_path)
                        
                        if points and len(points) > 1:
                            print(f"✓ GPX cargado: {len(points)} puntos")
                            
                            # Crear mapa temporal
                            route_map = optimizer.create_optimized_map(points, f"Navegación: {route.name}")
                            
                            # Generar HTML temporal en memoria
                            import tempfile
                            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as temp_file:
                                route_map.save(temp_file.name)
                                
                                # Leer contenido
                                with open(temp_file.name, 'r', encoding='utf-8') as f:
                                    map_html = f.read()
                                
                                # Limpiar archivo temporal
                                os.unlink(temp_file.name)
                            
                            map_source = "gpx_regenerated"
                            print(f"✓ Mapa regenerado desde GPX ({len(map_html)} caracteres)")
                            
                            # OPCIONAL: Guardar el mapa regenerado para futuro uso
                            try:
                                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                                new_filename = f"route_{route.id}_regenerated_{timestamp}.html"
                                new_filepath = os.path.join('static', 'routes', new_filename)
                                
                                os.makedirs(os.path.dirname(new_filepath), exist_ok=True)
                                
                                with open(new_filepath, 'w', encoding='utf-8') as f:
                                    f.write(map_html)
                                
                                # Actualizar BD con la nueva ruta
                                old_path = route.file_path
                                route.file_path = new_filepath
                                db.session.commit()
                                
                                print(f"✓ Mapa guardado para futuro uso: {new_filepath}")
                                
                                # Eliminar archivo anterior si existe
                                if old_path and os.path.exists(old_path):
                                    try:
                                        os.remove(old_path)
                                        print(f"✓ Archivo anterior eliminado: {old_path}")
                                    except:
                                        pass
                                        
                            except Exception as e:
                                print(f"⚠️  No se pudo guardar mapa regenerado: {e}")
                                # No es crítico, continuar con el mapa en memoria
                            
                        else:
                            print(f"✗ GPX no contiene puntos válidos")
                            
                    except Exception as e:
                        print(f"✗ Error procesando GPX: {e}")
                else:
                    print(f"✗ GPX no existe: {route.gpx_path}")
            
            # INTENTO 3: Crear mapa básico de fallback
            if not map_html:
                print("Intento 3: Creando mapa básico de fallback")
                
                try:
                    map_html = create_navigation_fallback_map(route)
                    map_source = "fallback"
                    print(f"✓ Mapa de fallback creado")
                    
                except Exception as e:
                    print(f"✗ Error creando fallback: {e}")
                    map_html = create_emergency_map_html(route.name)
                    map_source = "emergency"
                    print(f"✓ Mapa de emergencia creado")
            
            print(f"Mapa final: fuente={map_source}, tamaño={len(map_html) if map_html else 0}")
            
            return render_template('driver/navigate.html',
                                 route=route,
                                 completion=in_progress,
                                 map_html=map_html,
                                 map_source=map_source)  # Para debug
                                 
        except Exception as e:
            print(f"ERROR CRÍTICO en driver_navigate: {e}")
            import traceback
            traceback.print_exc()
            
            flash(f'Error al cargar la navegación: {str(e)}', 'danger')
            return redirect(url_for('driver_dashboard'))


    def create_fallback_map(route_name, error=None):
        """Crear un mapa básico como fallback"""
        try:
            import folium
            
            # Crear mapa centrado en Ecuador
            fallback_map = folium.Map(
                location=[-3.8167, -78.7500],
                zoom_start=13,
                tiles='OpenStreetMap'
            )
            
            # Agregar marcador básico
            folium.Marker(
                location=[-3.8167, -78.7500],
                popup=f'Ubicación de referencia para {route_name}',
                icon=folium.Icon(color='blue', icon='info-sign')
            ).add_to(fallback_map)
            
            # Mensaje de información
            info_message = f'''
            <div style="position: fixed; 
                        top: 10px; left: 10px; 
                        background-color: rgba(255, 193, 7, 0.9); 
                        padding: 10px; border-radius: 5px; 
                        z-index: 9999; max-width: 300px;">
                <h6>⚠️ Mapa Básico</h6>
                <p>No se pudo cargar la ruta completa.</p>
                {f"<p><small>Error: {error}</small></p>" if error else ""}
                <p><small>Puedes usar el GPS para navegación.</small></p>
            </div>
            '''
            
            fallback_map.get_root().html.add_child(folium.Element(info_message))
            
            # Generar HTML
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as temp_file:
                fallback_map.save(temp_file.name)
                
                with open(temp_file.name, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                
                os.unlink(temp_file.name)
                return html_content
                
        except Exception as e:
            print(f"Error creando mapa fallback: {e}")
            return f'''
            <div style="height: 400px; display: flex; align-items: center; justify-content: center; 
                        background-color: #f8f9fa; border: 1px solid #dee2e6;">
                <div class="text-center">
                    <h5>No se pudo cargar el mapa</h5>
                    <p class="text-muted">Error: {e}</p>
                    <p><small>Usa el GPS para navegación manual</small></p>
                </div>
            </div>
            '''




    @app.route('/driver/update_route_progress/<int:completion_id>', methods=['POST'])
    @driver_required
    def driver_update_route_progress(completion_id):
        try:
            completion = RouteCompletion.query.get_or_404(completion_id)
            
            if completion.driver_id != current_user.id:
                return jsonify({'success': False, 'message': 'No tienes permiso para actualizar este registro'}), 403
            
            if completion.status != 'in_progress':
                return jsonify({'success': False, 'message': 'Esta ruta no está en progreso'}), 400
            
            data = request.json
            if not data or 'position' not in data:
                return jsonify({'success': False, 'message': 'Datos de posición requeridos'}), 400
            
            position = data['position']
            
            if completion.track_data:
                track_data = json.loads(completion.track_data)
                track_data.append({
                    'lat': position['lat'],
                    'lng': position['lng'],
                    'timestamp': datetime.utcnow().isoformat()
                })
            else:
                track_data = [{
                    'lat': position['lat'],
                    'lng': position['lng'],
                    'timestamp': datetime.utcnow().isoformat()
                }]
            
            completion.track_data = json.dumps(track_data)
            db.session.commit()
            
            return jsonify({'success': True, 'message': 'Posición actualizada'})
            
        except Exception as e:
            print(f"ERROR en driver_update_route_progress: {e}")
            return jsonify({'success': False, 'message': f'Error al actualizar progreso: {str(e)}'}), 




    @app.route('/driver/complete_route/<int:completion_id>', methods=['POST'])
    @driver_required
    def driver_complete_route(completion_id):
        try:
            completion = RouteCompletion.query.get_or_404(completion_id)
            
            if completion.driver_id != current_user.id:
                return jsonify({'success': False, 'message': 'No tienes permiso para actualizar este registro'}), 403
            
            if completion.status != 'in_progress':
                return jsonify({'success': False, 'message': 'Esta ruta no está en progreso'}), 400
            
            data = request.json
            fuel_end = data.get('fuel_level') if data else None
            notes = data.get('notes') if data else None
            
            if not fuel_end or fuel_end not in [1, 2, 3, 4]:
                return jsonify({'success': False, 'message': 'Debes seleccionar el nivel final de combustible (1-4)'}), 400
            
            # Actualizar datos básicos de la completion
            completion.status = 'completed'
            completion.completed_at = datetime.utcnow()
            completion.fuel_end = fuel_end
            completion.fuel_consumption = completion.fuel_start - fuel_end
            
            if notes:
                completion.notes = notes
            
            db.session.commit()
            
            if completion.fuel_consumption > 0:
                consumption_msg = f"Consumo: {completion.fuel_consumption}/4 tanques"
            elif completion.fuel_consumption < 0:
                consumption_msg = f"¡Combustible aumentó! (posible recarga: +{abs(completion.fuel_consumption)}/4)"
            else:
                consumption_msg = "Sin cambio en el nivel de combustible"
            
            return jsonify({
                'success': True, 
                'message': f'Ruta completada exitosamente. {consumption_msg}',
                'has_map': completion.track_map_path is not None
            })
            
        except Exception as e:
            print(f"ERROR en driver_complete_route: {e}")
            return jsonify({'success': False, 'message': f'Error al completar ruta: {str(e)}'}), 500



    @app.route('/driver/cancel_route/<int:completion_id>', methods=['POST'])
    @driver_required
    def driver_cancel_route(completion_id):
        try:
            completion = RouteCompletion.query.get_or_404(completion_id)
            
            if completion.driver_id != current_user.id:
                return jsonify({'success': False, 'message': 'No tienes permiso para actualizar este registro'}), 403
            
            if completion.status != 'in_progress':
                return jsonify({'success': False, 'message': 'Esta ruta no está en progreso'}), 400
            
            completion.status = 'canceled'
            
            data = request.json
            if data and 'reason' in data:
                completion.notes = f"Cancelado: {data['reason']}"
            
            db.session.commit()
            
            return jsonify({
                'success': True, 
                'message': 'Ruta cancelada'
            })
            
        except Exception as e:
            print(f"ERROR en driver_cancel_route: {e}")
            return jsonify({'success': False, 'message': f'Error al cancelar ruta: {str(e)}'}), 500

        

    @app.route('/view_completion_map/<int:completion_id>')
    @login_required
    def view_completion_map(completion_id):
        """Ver el mapa del recorrido completado"""
        try:
            completion = RouteCompletion.query.get_or_404(completion_id)
            
            # Verificar permisos
            if not (current_user.is_admin or current_user.is_coordinator or 
                    (current_user.is_driver and completion.driver_id == current_user.id)):
                flash('No tienes permisos para ver este recorrido.', 'danger')
                return redirect(url_for('dashboard'))
            
            # Verificar si existe el mapa
            if not completion.track_map_path or not os.path.exists(completion.track_map_path):
                # Intentar generar el mapa si tenemos datos de tracking
                if completion.track_data:
                    try:
                        completion_map = generate_completion_map(completion)
                        if completion_map:
                            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                            map_filename = f"completion_{completion.id}_{timestamp}.html"
                            map_filepath = os.path.join('static', 'completions', map_filename)
                            
                            os.makedirs(os.path.dirname(map_filepath), exist_ok=True)
                            completion_map.save(map_filepath)
                            
                            completion.track_map_path = map_filepath
                            db.session.commit()
                    except Exception as e:
                        print(f"Error regenerando mapa: {e}")
                        flash('No se pudo cargar el mapa del recorrido.', 'warning')
                        return redirect(url_for('dashboard'))
                else:
                    flash('No hay datos de recorrido disponibles para esta ruta.', 'warning')
                    return redirect(url_for('dashboard'))
            
            # Cargar el contenido del mapa
            try:
                with open(completion.track_map_path, 'r', encoding='utf-8') as f:
                    map_html = f.read()
            except Exception as e:
                print(f"Error cargando archivo de mapa: {e}")
                map_html = "<p>No se pudo cargar el mapa del recorrido</p>"
            
            return render_template('view_completion_map.html',
                                completion=completion,
                                map_html=map_html)
            
        except Exception as e:
            print(f"ERROR en view_completion_map: {e}")
            flash(f'Error al cargar el mapa: {str(e)}', 'danger')
            return redirect(url_for('dashboard'))

    # ========================================
    # Función para servir archivos de mapas de recorridos
    # ========================================

    @app.route('/completions/<path:filename>')
    def completion_files(filename):
        """Servir archivos de mapas de recorridos completados"""
        return send_from_directory('static/completions', filename)




    # [Por brevedad, incluyo solo las rutas esenciales aquí]

    # ==================== RUTAS PARA REPORTES PDF ====================
    
    @app.route('/admin/download_report')
    @admin_required
    def download_admin_report():
        """Descargar reporte completo de administrador en PDF"""
        try:
            if PDFReportGenerator is None:
                flash('Generador de PDF no disponible. Contacta al administrador.', 'danger')
                return redirect(url_for('admin_dashboard'))
            
            # Obtener todos los datos necesarios
            metrics_data = get_metrics_data()
            fuel_data = get_fuel_data()
            vehicle_data = get_vehicle_performance_data()
            driver_data = get_driver_performance_data()
            route_data = get_route_performance_data()
            
            # Crear generador de PDF
            pdf_generator = PDFReportGenerator()
            
            # Generar reporte
            user_name = f"{current_user.first_name} {current_user.last_name}"
            pdf_buffer = pdf_generator.generate_admin_report(
                metrics_data, fuel_data, vehicle_data, driver_data, route_data, user_name
            )
            
            # Generar nombre de archivo con timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"reporte_administrativo_{timestamp}.pdf"
            
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=filename,
                mimetype='application/pdf'
            )
            
        except Exception as e:
            print(f"Error generando reporte admin: {e}")
            flash('Error al generar el reporte. Intenta de nuevo.', 'danger')
            return redirect(url_for('admin_dashboard'))

    @app.route('/coordinator/download_report')
    @coordinator_required
    def download_coordinator_report():
        """Descargar reporte de coordinador en PDF"""
        try:
            if PDFReportGenerator is None:
                flash('Generador de PDF no disponible. Contacta al administrador.', 'danger')
                return redirect(url_for('coordinator_dashboard'))
            
            # Obtener datos necesarios para coordinador
            metrics_data = get_metrics_data()
            fuel_data = get_fuel_data()
            driver_data = get_driver_performance_data()
            route_data = get_route_performance_data()
            
            # Crear generador de PDF
            pdf_generator = PDFReportGenerator()
            
            # Generar reporte
            user_name = f"{current_user.first_name} {current_user.last_name}"
            pdf_buffer = pdf_generator.generate_coordinator_report(
                metrics_data, fuel_data, driver_data, route_data, user_name
            )
            
            # Generar nombre de archivo con timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"reporte_coordinacion_{timestamp}.pdf"
            
            return send_file(
                pdf_buffer,
                as_attachment=True,
                download_name=filename,
                mimetype='application/pdf'
            )
            
        except Exception as e:
            print(f"Error generando reporte coordinador: {e}")
            flash('Error al generar el reporte. Intenta de nuevo.', 'danger')
            return redirect(url_for('coordinator_dashboard'))

    @app.route('/api/report/preview/<report_type>')
    @login_required
    def preview_report_data(report_type):
        """API para previsualizar datos del reporte antes de generar PDF"""
        try:
            if report_type not in ['admin', 'coordinator']:
                return jsonify({'error': 'Tipo de reporte inválido'}), 400
            
            # Verificar permisos
            if report_type == 'admin' and not current_user.is_admin:
                return jsonify({'error': 'Sin permisos para reporte admin'}), 403
            
            if report_type == 'coordinator' and not (current_user.is_coordinator or current_user.is_admin):
                return jsonify({'error': 'Sin permisos para reporte coordinador'}), 403
            
            # Obtener datos
            metrics_data = get_metrics_data()
            fuel_data = get_fuel_data()
            driver_data = get_driver_performance_data()
            route_data = get_route_performance_data()
            
            preview_data = {
                'report_type': report_type,
                'generated_at': datetime.now().isoformat(),
                'user': f"{current_user.first_name} {current_user.last_name}",
                'metrics': metrics_data,
                'fuel': fuel_data,
                'drivers': driver_data[:5],  # Top 5 para preview
                'routes': route_data[:5],    # Top 5 para preview
                'summary': {
                    'total_drivers': len(driver_data),
                    'total_routes': len(route_data),
                    'avg_driver_score': round(sum([d['score'] for d in driver_data]) / len(driver_data), 1) if driver_data else 0,
                    'best_efficiency': max([d['efficiency'] for d in driver_data]) if driver_data else 0
                }
            }
            
            # Agregar datos específicos para admin
            if report_type == 'admin':
                vehicle_data = get_vehicle_performance_data()
                preview_data['vehicles'] = vehicle_data[:5]
                preview_data['summary']['total_vehicles'] = len(vehicle_data)
            
            return jsonify(preview_data)
            
        except Exception as e:
            print(f"Error en preview_report_data: {e}")
            return jsonify({'error': str(e)}), 500

    # ==================== UTILIDADES ====================
    
    

    # ==================== API PARA MÉTRICAS DE COMBUSTIBLE ====================

    @app.route('/api/metrics/fuel-by-vehicle')
    @login_required
    def api_fuel_by_vehicle():
        try:
            fuel_data = db.session.query(
                Vehicle.brand,
                Vehicle.model,
                Vehicle.plate_number,
                db.func.count(RouteCompletion.id).label('total_routes'),
                db.func.sum(RouteCompletion.fuel_consumption).label('total_fuel_consumed'),
                db.func.avg(RouteCompletion.fuel_consumption).label('avg_fuel_consumption')
            ).join(
                RouteCompletion, Vehicle.id == RouteCompletion.vehicle_id
            ).filter(
                RouteCompletion.status == 'completed',
                RouteCompletion.fuel_consumption.isnot(None)
            ).group_by(
                Vehicle.id, Vehicle.brand, Vehicle.model, Vehicle.plate_number
            ).order_by(
                db.func.sum(RouteCompletion.fuel_consumption).desc()
            ).all()
            
            result = []
            for item in fuel_data:
                result.append({
                    'vehicle_name': f"{item.brand} {item.model}",
                    'plate_number': item.plate_number,
                    'total_routes': item.total_routes,
                    'total_fuel_consumed': float(item.total_fuel_consumed or 0),
                    'avg_fuel_consumption': round(float(item.avg_fuel_consumption or 0), 2),
                    'efficiency_score': round(item.total_routes / max(float(item.total_fuel_consumed or 1), 0.1), 2)
                })
            
            return jsonify(result)
        except Exception as e:
            print(f"Error en api_fuel_by_vehicle: {e}")
            return jsonify([])

    @app.route('/api/metrics/fuel-by-driver')
    @login_required
    def api_fuel_by_driver():
        """Consumo de combustible por chofer"""
        try:
            fuel_data = db.session.query(
                User.first_name,
                User.last_name,
                db.func.count(RouteCompletion.id).label('total_routes'),
                db.func.sum(RouteCompletion.fuel_consumption).label('total_fuel_consumed'),
                db.func.avg(RouteCompletion.fuel_consumption).label('avg_fuel_consumption')
            ).join(
                RouteCompletion, User.id == RouteCompletion.driver_id
            ).filter(
                User.role == 'driver',
                RouteCompletion.status == 'completed',
                RouteCompletion.fuel_consumption.isnot(None)
            ).group_by(
                User.id, User.first_name, User.last_name
            ).order_by(
                db.func.sum(RouteCompletion.fuel_consumption).desc()
            ).all()
            
            result = []
            for item in fuel_data:
                result.append({
                    'driver_name': f"{item.first_name} {item.last_name}",
                    'total_routes': item.total_routes,
                    'total_fuel_consumed': float(item.total_fuel_consumed or 0),
                    'avg_fuel_consumption': round(float(item.avg_fuel_consumption or 0), 2),
                    'efficiency_score': round(item.total_routes / max(float(item.total_fuel_consumed or 1), 0.1), 2)
                })
            
            return jsonify(result)
        except Exception as e:
            print(f"Error en api_fuel_by_driver: {e}")
            return jsonify([])

    @app.route('/api/vehicles/active-positions')
    @login_required
    def api_active_vehicle_positions():
        """API para obtener posiciones de vehículos activos"""
        try:
            active_completions = RouteCompletion.query.filter_by(
                status='in_progress'
            ).all()
            
            vehicles_data = []
            for completion in active_completions:
                if completion.vehicle and completion.driver and completion.route:
                    last_position = None
                    if completion.track_data:
                        try:
                            track_data = json.loads(completion.track_data)
                            if track_data:
                                last_position = track_data[-1]
                        except:
                            pass
                    
                    vehicle_info = {
                        'id': completion.id,
                        'vehicle_name': f"{completion.vehicle.brand} {completion.vehicle.model}",
                        'plate': completion.vehicle.plate_number,
                        'driver_name': f"{completion.driver.first_name} {completion.driver.last_name}",
                        'route_name': completion.route.name,
                        'status': 'active',
                        'fuel_level': completion.fuel_start or 4,
                        'started_at': completion.started_at.isoformat() if completion.started_at else None
                    }
                    
                    if last_position:
                        vehicle_info['lat'] = last_position.get('lat')
                        vehicle_info['lng'] = last_position.get('lng')
                    else:
                        vehicle_info['lat'] = -3.8167 + (random.uniform(-0.01, 0.01))
                        vehicle_info['lng'] = -78.7500 + (random.uniform(-0.01, 0.01))
                    
                    vehicles_data.append(vehicle_info)
            
            return jsonify(vehicles_data)
            
        except Exception as e:
            print(f"Error en api_active_vehicle_positions: {e}")
            return jsonify([])

    # Crear tablas al inicializar la aplicación
    
    def get_recent_completions(limit=10):
        """Obtener recorridos completados recientes"""
        try:
            return RouteCompletion.query.filter_by(
                status='completed'
            ).order_by(
                RouteCompletion.completed_at.desc()
            ).limit(limit).all()
        except Exception as e:
            print(f"Error obteniendo recorridos recientes: {e}")
            return []

    @app.route('/routes/<path:filename>')
    def route_files(filename):
        return send_from_directory('static/routes', filename)

    @app.route('/uploads/<path:filename>')
    def uploaded_files(filename):
        return send_from_directory('uploads', filename)

    @app.route('/reset_database')
    def reset_database():
        if app.debug:
            db.drop_all()
            db.create_all()
        
        # Solo crear el usuario administrador inicial
            admin = User(
                username='admin',
                email='admin@empresa.com',  # Cambia por el email real
                first_name='Administrador',
                last_name='Principal',
                cedula='000000001',  # Cambia por la cédula real
                role='admin'
            )
            admin.set_password('admin2024!')  # Cambia por una contraseña segura
        
            db.session.add(admin)
            db.session.commit()
        
            flash('Base de datos inicializada. Usuario administrador creado.', 'success')
        else:
            flash('Reset de base de datos solo disponible en modo debug.', 'danger')
    
        return redirect(url_for('login'))

    @app.route('/debug_users')
    def debug_users():
        if app.debug:
            users = User.query.all()
            user_list = []
            for user in users:
                user_list.append({
                    'username': user.username,
                    'role': user.role,
                    'active': user.active,
                    'id': user.id
                })
            return jsonify({
                'total_users': len(users),
                'users': user_list
            })
        else:
            return jsonify({'error': 'Solo disponible en modo debug'})

    @app.route('/debug_vehicles')
    def debug_vehicles():
        if app.debug:
            vehicles = Vehicle.query.all()
            vehicle_list = []
            for vehicle in vehicles:
                vehicle_list.append({
                    'brand': vehicle.brand,
                    'model': vehicle.model,
                    'plate': vehicle.plate_number,
                    'active': vehicle.active,
                    'id': vehicle.id
                })
            return jsonify({
                'total_vehicles': len(vehicles),
                'vehicles': vehicle_list
            })
        else:
            return jsonify({'error': 'Solo disponible en modo debug'})
        
    @app.route('/api/route/optimization-metrics/<int:route_id>')
    @login_required
    def get_route_optimization_metrics(route_id):
        """Obtener métricas de optimización de una ruta"""
        try:
            route = Route.query.get_or_404(route_id)
            
            if not route.gpx_path or not os.path.exists(route.gpx_path):
                return jsonify({'error': 'Archivo GPX no encontrado'}), 404
            
            optimizer = AdvancedRouteOptimizer()
            
            # Cargar puntos originales
            original_points = optimizer.load_gpx_points(route.gpx_path)
            
            # Simular optimización para obtener métricas
            optimal_path, _ = optimizer.optimize_route_advanced([route.gpx_path], 'advanced')
            
            # Calcular métricas
            validation_metrics = optimizer.validate_optimization(original_points, optimal_path)
            
            # Detectar bucles
            original_loops = optimizer.detect_loops(original_points)
            optimized_loops = optimizer.detect_loops(optimal_path)
            
            return jsonify({
                'route_name': route.name,
                'metrics': validation_metrics,
                'can_optimize': validation_metrics['distance_reduction_percent'] > 1,
                'optimization_potential': {
                    'distance_saving': validation_metrics['distance_reduction_km'],
                    'percentage_improvement': validation_metrics['distance_reduction_percent'],
                    'loops_to_remove': len(original_loops),
                    'points_to_reduce': validation_metrics['points_reduction']
                }
            })
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        

    # Agrega esta ruta de debug a tu app.py para probar el optimizador

    @app.route('/debug/test_optimizer')
    def test_optimizer():
        """Ruta de debug para probar el optimizador sin formulario"""
        if not app.debug:
            return jsonify({'error': 'Solo disponible en modo debug'})
        
        try:
            print("=== INICIANDO TEST DEL OPTIMIZADOR ===")
            
            # Crear puntos de prueba
            test_points = [
                (-3.8167, -78.7500),
                (-3.8170, -78.7503),
                (-3.8173, -78.7506),
                (-3.8176, -78.7509),
                (-3.8179, -78.7512)
            ]
            
            print(f"Puntos de prueba creados: {len(test_points)}")
            
            # Probar importación del optimizador
            from services.route_optimizer import AdvancedRouteOptimizer
            print("✓ Optimizador importado correctamente")
            
            # Crear instancia
            optimizer = AdvancedRouteOptimizer()
            print("✓ Instancia del optimizador creada")
            
            # Probar cálculo de distancia
            distance = optimizer.calculate_total_distance(test_points)
            print(f"✓ Distancia total calculada: {distance} metros")
            
            # Probar detección de bucles
            loops = optimizer.detect_loops(test_points)
            print(f"✓ Bucles detectados: {len(loops)}")
            
            # Probar creación de mapa
            route_map = optimizer.create_optimized_map(test_points, "Ruta de Prueba")
            print("✓ Mapa creado correctamente")
            
            # Probar métricas de validación
            validation = optimizer.validate_optimization(test_points, test_points)
            print(f"✓ Métricas de validación: {validation}")
            
            return jsonify({
                'status': 'success',
                'message': 'Optimizador funcionando correctamente',
                'test_results': {
                    'points_count': len(test_points),
                    'total_distance': distance,
                    'loops_detected': len(loops),
                    'validation_metrics': validation
                }
            })
            
        except ImportError as e:
            print(f"ERROR de importación: {e}")
            return jsonify({
                'status': 'error',
                'type': 'import_error',
                'message': f'Error importando el optimizador: {str(e)}'
            })
            
        except Exception as e:
            print(f"ERROR general: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'status': 'error',
                'type': 'general_error',
                'message': str(e)
            })
        


    @app.route('/download_completion_map/<int:completion_id>')
    @login_required
    def download_completion_map(completion_id):
        """Descargar el mapa del recorrido como archivo HTML"""
        try:
            completion = RouteCompletion.query.get_or_404(completion_id)
            
            # Verificar permisos
            if not (current_user.is_admin or current_user.is_coordinator or 
                    (current_user.is_driver and completion.driver_id == current_user.id)):
                flash('No tienes permisos para descargar este mapa.', 'danger')
                return redirect(url_for('dashboard'))
            
            if not completion.track_map_path or not os.path.exists(completion.track_map_path):
                flash('El mapa no está disponible para descarga.', 'warning')
                return redirect(url_for('dashboard'))
            
            # Generar nombre de archivo
            filename = f"recorrido_{completion.route.name}_{completion.completed_at.strftime('%Y%m%d')}.html"
            filename = "".join(c for c in filename if c.isalnum() or c in '._-')
            
            return send_file(
                completion.track_map_path,
                as_attachment=True,
                download_name=filename,
                mimetype='text/html'
            )
            
        except Exception as e:
            print(f"Error descargando mapa: {e}")
            flash(f'Error al descargar el mapa: {str(e)}', 'danger')
            return redirect(url_for('dashboard'))



    @app.route('/api/completion-stats/<int:completion_id>')
    @login_required
    def api_completion_stats(completion_id):
        """API para obtener estadísticas detalladas de un recorrido"""
        try:
            completion = RouteCompletion.query.get_or_404(completion_id)
            
            # Verificar permisos
            if not (current_user.is_admin or current_user.is_coordinator or 
                    (current_user.is_driver and completion.driver_id == current_user.id)):
                return jsonify({'error': 'Sin permisos'}), 403
            
            stats = {
                'completion_id': completion.id,
                'route_name': completion.route.name,
                'driver_name': f"{completion.driver.first_name} {completion.driver.last_name}",
                'vehicle_info': f"{completion.vehicle.brand} {completion.vehicle.model} ({completion.vehicle.plate_number})",
                'started_at': completion.started_at.isoformat() if completion.started_at else None,
                'completed_at': completion.completed_at.isoformat() if completion.completed_at else None,
                'fuel_start': completion.fuel_start,
                'fuel_end': completion.fuel_end,
                'fuel_consumption': completion.fuel_consumption,
                'notes': completion.notes,
                'has_map': completion.track_map_path is not None and os.path.exists(completion.track_map_path) if completion.track_map_path else False
            }
            
            # Calcular estadísticas del tracking si hay datos
            if completion.track_data:
                try:
                    track_points = json.loads(completion.track_data)
                    stats['tracking'] = {
                        'total_points': len(track_points),
                        'first_point': track_points[0] if track_points else None,
                        'last_point': track_points[-1] if track_points else None
                    }
                    
                    # Calcular duración y frecuencia promedio
                    if completion.started_at and completion.completed_at and len(track_points) > 1:
                        duration_seconds = (completion.completed_at - completion.started_at).total_seconds()
                        stats['tracking']['duration_seconds'] = duration_seconds
                        stats['tracking']['avg_tracking_interval'] = duration_seconds / (len(track_points) - 1)
                        stats['tracking']['tracking_frequency'] = f"{stats['tracking']['avg_tracking_interval']:.1f} segundos"
                    
                except Exception as e:
                    print(f"Error procesando datos de tracking: {e}")
                    stats['tracking'] = {'error': 'Error procesando datos de tracking'}
            
            # Calcular eficiencia si hay datos de la ruta original
            if completion.route.distance:
                stats['route'] = {
                    'planned_distance_m': completion.route.distance,
                    'planned_distance_km': completion.route.distance / 1000
                }
                
                # Calcular eficiencia de combustible
                if completion.fuel_consumption and completion.fuel_consumption > 0:
                    # Aproximar galones por tanque (esto puede variar según el vehículo)
                    gallons_per_tank = 10  # Ajustar según tus vehículos
                    total_gallons = completion.fuel_consumption * gallons_per_tank
                    km_per_gallon = (completion.route.distance / 1000) / total_gallons
                    stats['efficiency'] = {
                        'km_per_gallon': round(km_per_gallon, 2),
                        'gallons_consumed': total_gallons,
                        'efficiency_rating': 'Excelente' if km_per_gallon > 15 else 'Buena' if km_per_gallon > 10 else 'Regular'
                    }
            
            return jsonify(stats)
            
        except Exception as e:
            print(f"Error en api_completion_stats: {e}")
            return jsonify({'error': str(e)}), 500

    # ========================================
    # RUTA PARA COMPARAR MÚLTIPLES RECORRIDOS
    # ========================================

    @app.route('/compare_completions')
    @login_required
    def compare_completions():
        """Página para comparar múltiples recorridos"""
        if not (current_user.is_admin or current_user.is_coordinator):
            flash('No tienes permisos para acceder a esta función.', 'danger')
            return redirect(url_for('dashboard'))
        
        # Obtener todas las rutas para filtrar
        routes = Route.query.filter_by(active=True).all()
        
        # Obtener recorridos completados con mapas
        completions = RouteCompletion.query.filter(
            RouteCompletion.status == 'completed',
            RouteCompletion.track_data.isnot(None)
        ).order_by(RouteCompletion.completed_at.desc()).limit(50).all()
        
        return render_template('compare_completions.html', 
                            routes=routes, 
                            completions=completions)

    # ========================================
    # MIGRACIÓN DE BASE DE DATOS
    # ========================================

    @app.route('/admin/migrate_completion_maps')
    @admin_required
    def migrate_completion_maps():
        """Generar mapas para recorridos completados que no los tienen"""
        try:
            # Buscar completions sin mapas pero con datos de tracking
            completions_without_maps = RouteCompletion.query.filter(
                RouteCompletion.status == 'completed',
                RouteCompletion.track_data.isnot(None),
                db.or_(
                    RouteCompletion.track_map_path.is_(None),
                    RouteCompletion.track_map_path == ''
                )
            ).all()
            
            generated_count = 0
            error_count = 0
            
            for completion in completions_without_maps:
                try:
                    # Generar mapa
                    completion_map = generate_completion_map(completion)
                    
                    if completion_map:
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                        map_filename = f"completion_{completion.id}_{timestamp}.html"
                        map_filepath = os.path.join('static', 'completions', map_filename)
                        
                        os.makedirs(os.path.dirname(map_filepath), exist_ok=True)
                        completion_map.save(map_filepath)
                        
                        completion.track_map_path = map_filepath
                        generated_count += 1
                        
                except Exception as e:
                    print(f"Error generando mapa para completion {completion.id}: {e}")
                    error_count += 1
                    continue
            
            db.session.commit()
            
            flash(f'Migración completada: {generated_count} mapas generados, {error_count} errores.', 'success')
            return redirect(url_for('admin_dashboard'))
            
        except Exception as e:
            print(f"Error en migración: {e}")
            flash(f'Error durante la migración: {str(e)}', 'danger')
            return redirect(url_for('admin_dashboard'))

    # ========================================
    # LIMPIEZA DE ARCHIVOS HUÉRFANOS
    # ========================================

    @app.route('/admin/cleanup_completion_maps')
    @admin_required
    def cleanup_completion_maps():
        """Limpiar archivos de mapas que ya no tienen referencias en la BD"""
        try:
            import glob
            
            # Obtener todos los archivos de mapas de completions
            completion_files = glob.glob('static/completions/*.html')
            
            # Obtener todas las rutas de mapas en la BD
            db_map_paths = set()
            completions_with_maps = RouteCompletion.query.filter(
                RouteCompletion.track_map_path.isnot(None)
            ).all()
            
            for completion in completions_with_maps:
                if completion.track_map_path:
                    db_map_paths.add(os.path.abspath(completion.track_map_path))
            
            # Encontrar archivos huérfanos
            orphaned_files = []
            for file_path in completion_files:
                abs_file_path = os.path.abspath(file_path)
                if abs_file_path not in db_map_paths:
                    orphaned_files.append(file_path)
            
            # Eliminar archivos huérfanos
            deleted_count = 0
            for file_path in orphaned_files:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    print(f"Error eliminando {file_path}: {e}")
            
            flash(f'Limpieza completada: {deleted_count} archivos huérfanos eliminados.', 'success')
            return redirect(url_for('admin_dashboard'))
            
        except Exception as e:
            print(f"Error en limpieza: {e}")
            flash(f'Error durante la limpieza: {str(e)}', 'danger')
            return redirect(url_for('admin_dashboard'))



    @app.route('/admin/migrate_database')
    @admin_required
    def migrate_database():
        """Migrar base de datos agregando columnas de optimización"""
        try:
            print("=== INICIANDO MIGRACIÓN ===")
            
            # Comandos SQL para agregar las columnas
            migration_sql = [
                "ALTER TABLE route ADD COLUMN original_distance REAL",
                "ALTER TABLE route ADD COLUMN distance_saved_km REAL", 
                "ALTER TABLE route ADD COLUMN distance_saved_percent REAL",
                "ALTER TABLE route ADD COLUMN estimated_time_saved_minutes INTEGER",
                "ALTER TABLE route ADD COLUMN optimization_level TEXT",
                "ALTER TABLE route ADD COLUMN loops_removed INTEGER",
                "ALTER TABLE route ADD COLUMN points_reduced INTEGER",
                "ALTER TABLE route_completion ADD COLUMN track_map_path TEXT"
            ]
            
            success_count = 0
            already_exists_count = 0
            errors = []
            
            for sql in migration_sql:
                try:
                    db.engine.execute(sql)
                    success_count += 1
                    print(f"✓ {sql}")
                except Exception as e:
                    error_str = str(e).lower()
                    if "duplicate column" in error_str or "already exists" in error_str:
                        already_exists_count += 1
                        print(f"- Ya existe: {sql}")
                    else:
                        errors.append(f"{sql}: {str(e)}")
                        print(f"✗ Error: {sql} - {str(e)}")
            
            print(f"=== RESULTADO ===")
            print(f"Exitosos: {success_count}")
            print(f"Ya existían: {already_exists_count}")
            print(f"Errores: {len(errors)}")
            
            if success_count > 0:
                flash(f'Migración exitosa: {success_count} columnas agregadas, {already_exists_count} ya existían', 'success')
            elif already_exists_count > 0:
                flash(f'Todas las columnas ya existen ({already_exists_count}). Base de datos actualizada.', 'info')
            
            if errors:
                flash(f'Algunos errores ocurrieron: {"; ".join(errors)}', 'warning')
            
            return redirect(url_for('admin_dashboard'))
            
        except Exception as e:
            print(f"Error general en migración: {e}")
            flash(f'Error en migración: {str(e)}', 'danger')
            return redirect(url_for('admin_dashboard'))

        

    @app.route('/admin/route-optimization/<int:route_id>')  # <- NOMBRE DIFERENTE
    @login_required
    def admin_view_route_optimization(route_id):
        """Ver detalles de optimización de ruta (versión segura)"""
        try:
            # Verificar si las columnas de optimización existen
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('route')]
            
            if 'distance_saved_km' not in columns:
                flash('Las métricas de optimización no están disponibles. Ejecuta la migración primero.', 'warning')
                return redirect(url_for('admin_dashboard'))
            
            route = Route.query.get_or_404(route_id)
            
            # Verificar permisos
            if not (current_user.is_admin or current_user.is_coordinator):
                flash('No tienes permisos para ver estos detalles.', 'danger')
                return redirect(url_for('dashboard'))
            
            # Si no hay datos de optimización, mostrar mensaje
            if not route.distance_saved_km or route.distance_saved_km <= 0:
                flash('Esta ruta no tiene datos de optimización disponibles.', 'info')
                return redirect(url_for('admin_view_route', route_id=route_id))
            
            # Calcular métricas adicionales
            optimization_metrics = {
                'route': route,
                'has_optimization_data': True,
                'efficiency_rating': 'Excelente' if (route.distance_saved_percent or 0) > 15 else 
                                'Buena' if (route.distance_saved_percent or 0) > 5 else 
                                'Regular' if (route.distance_saved_percent or 0) > 0 else 
                                'Sin optimización'
            }
            
            return render_template('optimization_details.html', metrics=optimization_metrics)
            
        except Exception as e:
            print(f"Error en admin_view_route_optimization: {e}")
            flash(f'Error al cargar detalles: {str(e)}', 'danger')
            return redirect(url_for('manage_routes'))

    @app.route('/admin/optimization-dashboard-view')  # <- NOMBRE DIFERENTE
    @admin_required  
    def admin_optimization_dashboard():
        """Dashboard de optimización (versión segura)"""
        try:
            # Verificar si las columnas existen
            inspector = db.inspect(db.engine)
            columns = [col['name'] for col in inspector.get_columns('route')]
            
            if 'distance_saved_km' not in columns:
                flash('Las métricas de optimización no están disponibles. Ejecuta la migración de base de datos primero.', 'warning')
                return redirect(url_for('admin_dashboard'))
            
            # Obtener datos de optimización
            optimization_summary = get_optimization_summary()
            
            # Obtener rutas mejor optimizadas
            top_routes = Route.query.filter(
                Route.active == True,
                Route.distance_saved_percent.isnot(None),
                Route.distance_saved_percent > 0
            ).order_by(Route.distance_saved_percent.desc()).limit(5).all()
            
            return render_template('admin/optimization_dashboard.html',
                                optimization_summary=optimization_summary,
                                top_routes=top_routes)
            
        except Exception as e:
            print(f"Error en admin_optimization_dashboard: {e}")
            flash(f'Error al cargar dashboard de optimización: {str(e)}', 'danger')
            return redirect(url_for('admin_dashboard'))

    @app.route('/debug/check_route_files/<int:route_id>')
    def debug_check_route_files(route_id):
        """Debug: Verificar archivos de una ruta específica"""
        if not app.debug:
            return jsonify({'error': 'Solo disponible en modo debug'})
        
        try:
            route = Route.query.get_or_404(route_id)
            
            result = {
                'route_id': route.id,
                'route_name': route.name,
                'file_path': route.file_path,
                'gpx_path': route.gpx_path,
                'checks': {}
            }
            
            # Verificar file_path (mapa HTML)
            if route.file_path:
                result['checks']['file_path_exists'] = os.path.exists(route.file_path)
                if os.path.exists(route.file_path):
                    result['checks']['file_size'] = os.path.getsize(route.file_path)
                    # Leer primeros 200 caracteres para verificar contenido
                    try:
                        with open(route.file_path, 'r', encoding='utf-8') as f:
                            content_preview = f.read(200)
                            result['checks']['file_content_preview'] = content_preview
                            result['checks']['is_html'] = '<html' in content_preview.lower()
                    except Exception as e:
                        result['checks']['file_read_error'] = str(e)
                else:
                    result['checks']['file_path_error'] = 'Archivo no encontrado'
            else:
                result['checks']['file_path_error'] = 'No file_path definido'
            
            # Verificar gpx_path
            if route.gpx_path:
                result['checks']['gpx_path_exists'] = os.path.exists(route.gpx_path)
                if os.path.exists(route.gpx_path):
                    result['checks']['gpx_size'] = os.path.getsize(route.gpx_path)
                    
                    # Intentar cargar puntos del GPX
                    try:
                        optimizer = AdvancedRouteOptimizer()
                        points = optimizer.load_gpx_points(route.gpx_path)
                        result['checks']['gpx_points_loaded'] = len(points)
                        result['checks']['sample_points'] = points[:3] if points else []
                    except Exception as e:
                        result['checks']['gpx_load_error'] = str(e)
                else:
                    result['checks']['gpx_path_error'] = 'Archivo GPX no encontrado'
            else:
                result['checks']['gpx_path_error'] = 'No gpx_path definido'
            
            return jsonify(result)
            
        except Exception as e:
            return jsonify({'error': str(e)})

    @app.route('/debug/regenerate_route_map/<int:route_id>')
    def debug_regenerate_route_map(route_id):
        """Debug: Regenerar mapa de una ruta desde GPX"""
        if not app.debug:
            return jsonify({'error': 'Solo disponible en modo debug'})
        
        try:
            route = Route.query.get_or_404(route_id)
            
            if not route.gpx_path or not os.path.exists(route.gpx_path):
                return jsonify({'error': 'No hay archivo GPX disponible'})
            
            print(f"Regenerando mapa para ruta: {route.name}")
            
            # Cargar puntos del GPX
            optimizer = AdvancedRouteOptimizer()
            points = optimizer.load_gpx_points(route.gpx_path)
            
            if not points:
                return jsonify({'error': 'No se pudieron cargar puntos del GPX'})
            
            # Crear nuevo mapa
            route_map = optimizer.create_optimized_map(points, route.name)
            
            # Generar nuevo archivo
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            new_filename = f"route_{route.id}_{timestamp}.html"
            new_filepath = os.path.join('static', 'routes', new_filename)
            
            # Asegurar que el directorio existe
            os.makedirs(os.path.dirname(new_filepath), exist_ok=True)
            
            # Guardar mapa
            route_map.save(new_filepath)
            
            # Actualizar ruta en BD
            old_file_path = route.file_path
            route.file_path = new_filepath
            db.session.commit()
            
            # Eliminar archivo anterior si existe
            if old_file_path and os.path.exists(old_file_path):
                try:
                    os.remove(old_file_path)
                except:
                    pass
            
            return jsonify({
                'success': True,
                'message': f'Mapa regenerado exitosamente',
                'new_file_path': new_filepath,
                'points_loaded': len(points),
                'file_size': os.path.getsize(new_filepath)
            })
            
        except Exception as e:
            print(f"Error regenerando mapa: {e}")
            return jsonify({'error': str(e)})

    @app.route('/debug/list_route_files')
    def debug_list_route_files():
        """Debug: Listar el estado de archivos de todas las rutas"""
        if not app.debug:
            return jsonify({'error': 'Solo disponible en modo debug'})
        
        try:
            routes = Route.query.filter_by(active=True).all()
            
            result = []
            for route in routes:
                route_info = {
                    'id': route.id,
                    'name': route.name,
                    'file_path': route.file_path,
                    'gpx_path': route.gpx_path,
                    'file_exists': route.file_path and os.path.exists(route.file_path) if route.file_path else False,
                    'gpx_exists': route.gpx_path and os.path.exists(route.gpx_path) if route.gpx_path else False,
                    'created_at': route.created_at.isoformat() if route.created_at else None
                }
                
                # Agregar tamaños de archivo
                if route_info['file_exists']:
                    route_info['file_size'] = os.path.getsize(route.file_path)
                
                if route_info['gpx_exists']:
                    route_info['gpx_size'] = os.path.getsize(route.gpx_path)
                
                result.append(route_info)
            
            return jsonify({
                'total_routes': len(routes),
                'routes_with_maps': len([r for r in result if r['file_exists']]),
                'routes_with_gpx': len([r for r in result if r['gpx_exists']]),
                'routes': result
            })
            
        except Exception as e:
            return jsonify({'error': str(e)})


    


    @app.route('/test')
    def test():
        return jsonify({
            'status': 'OK',
            'message': 'El servidor está funcionando correctamente',
            'timestamp': datetime.now().isoformat()
        })

    with app.app_context():
        db.create_all()
    
    return app

if __name__ == '__main__':
    app = create_app()