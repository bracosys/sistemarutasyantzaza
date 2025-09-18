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

# Importar el generador de PDF (se crear√° despu√©s)
try:
    from services.pdf_generator import PDFReportGenerator
except ImportError:
    PDFReportGenerator = None
    print("Warning: PDF generator not available. Create services/pdf_generator.py")

# Inicializaci√≥n de extensiones
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
    vehicle = db.relationship('Vehicle', backref='route_completions')

# ==================== DECORADORES DE AUTORIZACI√ìN ====================

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Debes iniciar sesi√≥n para acceder a esta p√°gina.', 'danger')
                return redirect(url_for('login'))
            
            if current_user.role not in roles:
                flash('No tienes permisos para acceder a esta p√°gina.', 'danger')
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

# ==================== FUNCIONES PARA M√âTRICAS Y REPORTES ====================

def get_metrics_data():
    """Obtener datos consolidados de m√©tricas"""
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
    """Obtener datos de rendimiento por veh√≠culo"""
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

# ==================== CREACI√ìN DE LA APLICACI√ìN ====================

def create_app():
    app = Flask(__name__)
    
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'clave_secreta_para_flask')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///app.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['UPLOAD_FOLDER'] = './uploads'
    
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs('static/routes', exist_ok=True)
    
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'login'
    login_manager.login_message = 'Por favor inicia sesi√≥n para acceder a esta p√°gina'
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
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
                flash('¬°Inicio de sesi√≥n exitoso!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Usuario o contrase√±a incorrectos.', 'danger')
        
        return render_template('login.html', now=datetime.now())

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('Has cerrado sesi√≥n correctamente.', 'success')
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
        
        return render_template('admin/dashboard.html', 
                             total_users=total_users,
                             total_drivers=total_drivers,
                             total_vehicles=total_vehicles, 
                             total_routes=total_routes,
                             recent_routes=recent_routes,
                             completed_routes=completed_routes,
                             in_progress_routes=in_progress_routes)

    # [Contin√∫a con todas las rutas del administrador...]
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
                flash('El email ya est√° registrado.', 'danger')
                return redirect(url_for('create_user'))
            
            if User.query.filter_by(cedula=cedula).first():
                flash('La c√©dula ya est√° registrada.', 'danger')
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

    

    # Reemplaza tu funci√≥n create_route en app.py con esta versi√≥n mejorada:

    # Reemplaza tu funci√≥n create_route en app.py con esta versi√≥n mejorada:

    @app.route('/admin/create_route', methods=['GET', 'POST'])
    @admin_required
    def create_route():
        if request.method == 'POST':
            print("=== INICIANDO CREACI√ìN DE RUTA ===")
            
            try:
                files = request.files.getlist('gpx_files')
                route_name = request.form.get('route_name')
                route_description = request.form.get('route_description')
                optimization_level = request.form.get('optimization_level', 'medium')
                
                print(f"Nombre de ruta: {route_name}")
                print(f"Descripci√≥n: {route_description}")
                print(f"Nivel de optimizaci√≥n: {optimization_level}")
                print(f"Archivos recibidos: {len(files)}")
                
                # Validaciones b√°sicas
                if not route_name or not files:
                    flash('Nombre de ruta y archivos GPX son requeridos.', 'danger')
                    return redirect(url_for('create_route'))
                
                if Route.query.filter_by(name=route_name).first():
                    flash('Ya existe una ruta con ese nombre.', 'danger')
                    return redirect(url_for('create_route'))
                
                # Verificar que tenemos archivos v√°lidos
                valid_files = [f for f in files if f.filename and f.filename.endswith('.gpx')]
                if not valid_files:
                    flash('No se subieron archivos GPX v√°lidos.', 'danger')
                    return redirect(url_for('create_route'))
                
                print(f"Archivos GPX v√°lidos: {len(valid_files)}")
                
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
                    
                    # Verificar que el archivo se guard√≥ correctamente
                    if os.path.exists(filepath):
                        file_size = os.path.getsize(filepath)
                        print(f"Tama√±o del archivo: {file_size} bytes")
                        
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
                
                print(f"Iniciando optimizaci√≥n de ruta '{route_name}' con nivel: {optimization_level}")
                
                # Cargar puntos originales para comparaci√≥n
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
                
                # Optimizar ruta
                print("\n=== OPTIMIZANDO RUTA ===")
                try:
                    # Intentar optimizaci√≥n normal primero
                    optimal_path, total_distance = optimizer.optimize_route_advanced(
                        uploaded_files, 
                        optimize_level=optimization_level
                    )
                except Exception as e:
                    print(f"Error en optimizaci√≥n avanzada: {e}")
                    print("Intentando optimizaci√≥n r√°pida...")
                    try:
                        # Usar optimizaci√≥n r√°pida como respaldo
                        optimal_path, total_distance = optimizer.optimize_route_quick(
                            uploaded_files, 
                            optimize_level='basic'
                        )
                    except Exception as e2:
                        print(f"Error en optimizaci√≥n r√°pida: {e2}")
                        # Como √∫ltimo recurso, usar solo los puntos originales
                        optimal_path = original_points
                        total_distance = optimizer.calculate_total_distance(original_points)
                        print("Usando puntos originales sin optimizaci√≥n")
                
                print(f"Optimizaci√≥n completada:")
                print(f"  - Puntos finales: {len(optimal_path)}")
                print(f"  - Distancia total: {total_distance} metros")
                
                # Validar optimizaci√≥n
                print("\n=== VALIDANDO OPTIMIZACI√ìN ===")
                validation_metrics = optimizer.validate_optimization(original_points, optimal_path)
                
                print(f"M√©tricas de optimizaci√≥n:")
                for key, value in validation_metrics.items():
                    print(f"  - {key}: {value}")
                
                # Crear mapa optimizado
                print("\n=== CREANDO MAPA ===")
                route_map = optimizer.create_optimized_map(optimal_path, route_name)
                
                # Guardar mapa
                map_filename = f"route_{uuid.uuid4().hex}.html"
                map_filepath = os.path.join('static', 'routes', map_filename)
                
                print(f"Guardando mapa en: {map_filepath}")
                
                # Asegurar que el directorio existe
                os.makedirs(os.path.dirname(map_filepath), exist_ok=True)
                
                route_map.save(map_filepath)
                
                # Verificar que el mapa se guard√≥
                if os.path.exists(map_filepath):
                    map_size = os.path.getsize(map_filepath)
                    print(f"Mapa guardado exitosamente, tama√±o: {map_size} bytes")
                else:
                    print("ERROR: No se pudo guardar el mapa")
                    flash('Error al guardar el mapa de la ruta.', 'danger')
                    return redirect(url_for('create_route'))
                
                # Crear nueva ruta en base de datos
                print("\n=== GUARDANDO EN BASE DE DATOS ===")
                new_route = Route(
                    name=route_name,
                    description=route_description,
                    creator_id=current_user.id,
                    file_path=map_filepath,
                    gpx_path=original_gpx_path,
                    start_point=f"{optimal_path[0][0]},{optimal_path[0][1]}",
                    end_point=f"{optimal_path[-1][0]},{optimal_path[-1][1]}",
                    distance=total_distance
                )
                
                db.session.add(new_route)
                db.session.commit()
                
                print(f"Ruta guardada en BD con ID: {new_route.id}")
                
                # Mensaje de √©xito con m√©tricas
                success_message = f'''Ruta "{route_name}" creada exitosamente. 
                                    Optimizaci√≥n completada: 
                                    {validation_metrics['distance_reduction_km']:.2f} km reducidos 
                                    ({validation_metrics['distance_reduction_percent']:.1f}% de mejora), 
                                    {validation_metrics['loops_removed']} bucles eliminados.'''
                
                print("=== RUTA CREADA EXITOSAMENTE ===")
                flash(success_message, 'success')
                return redirect(url_for('manage_routes'))
                
            except Exception as e:
                print(f"\n=== ERROR EN CREACI√ìN DE RUTA ===")
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

    @app.route('/admin/view_vehicle/<int:vehicle_id>')
    @admin_required
    def admin_view_vehicle(vehicle_id):
        vehicle = Vehicle.query.get_or_404(vehicle_id)
        
        # Obtener asignaciones del veh√≠culo
        assignments = VehicleAssignment.query.filter_by(vehicle_id=vehicle_id).order_by(VehicleAssignment.assigned_at.desc()).all()
        
        # Obtener completados de rutas con este veh√≠culo
        route_completions = RouteCompletion.query.filter_by(vehicle_id=vehicle_id).order_by(RouteCompletion.completed_at.desc()).all()
        
        # Estad√≠sticas del veh√≠culo
        total_routes = len(route_completions)
        completed_routes = len([rc for rc in route_completions if rc.status == 'completed'])
        total_distance = sum([rc.route.distance or 0 for rc in route_completions if rc.status == 'completed'])
        
        return render_template('admin/view_vehicle.html', 
                             vehicle=vehicle,
                             assignments=assignments,
                             route_completions=route_completions,
                             total_routes=total_routes,
                             completed_routes=completed_routes,
                             total_distance=total_distance)

    @app.route('/admin/add_vehicle', methods=['GET', 'POST'])
    @admin_required
    def add_vehicle():
        if request.method == 'POST':
            brand = request.form.get('brand')
            model = request.form.get('model')
            year = request.form.get('year')
            plate_number = request.form.get('plate_number')
            
            if Vehicle.query.filter_by(plate_number=plate_number).first():
                flash('Ya existe un veh√≠culo con esa placa.', 'danger')
                return redirect(url_for('add_vehicle'))
            
            new_vehicle = Vehicle(
                brand=brand,
                model=model,
                year=year,
                plate_number=plate_number
            )
            
            db.session.add(new_vehicle)
            db.session.commit()
            
            flash('Veh√≠culo a√±adido correctamente.', 'success')
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
                    flash('Ya existe un veh√≠culo con esa placa.', 'danger')
                    return redirect(url_for('edit_vehicle', vehicle_id=vehicle_id))
                
                vehicle.plate_number = plate_number
                db.session.commit()
                
                flash('Veh√≠culo actualizado correctamente.', 'success')
                return redirect(url_for('manage_vehicles'))
            
            return render_template('admin/edit_vehicle.html', vehicle=vehicle)
            
        except Exception as e:
            print(f"ERROR en edit_vehicle: {e}")
            flash(f'Error al editar el veh√≠culo: {str(e)}', 'danger')
            return redirect(url_for('manage_vehicles'))

    @app.route('/admin/toggle_vehicle/<int:vehicle_id>', methods=['POST'])
    @admin_required
    def toggle_vehicle_status(vehicle_id):
        try:
            vehicle = Vehicle.query.get_or_404(vehicle_id)
            vehicle.active = not vehicle.active
            db.session.commit()
            
            status = 'activado' if vehicle.active else 'desactivado'
            flash(f'Veh√≠culo {status} correctamente.', 'success')
            return redirect(url_for('manage_vehicles'))
            
        except Exception as e:
            print(f"ERROR en toggle_vehicle_status: {e}")
            flash(f'Error al cambiar estado del veh√≠culo: {str(e)}', 'danger')
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

    # ==================== RUTAS DE T√âCNICO ====================
    
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
                flash('Las contrase√±as no coinciden.', 'danger')
                return redirect(url_for('change_user_password', user_id=user_id))
            
            user.set_password(new_password)
            db.session.commit()
            
            flash(f'Contrase√±a de {user.username} actualizada correctamente.', 'success')
            return redirect(url_for('technician_dashboard'))
        
        return render_template('technician/change_password.html', user=user)

    @app.route('/technician/toggle_user/<int:user_id>', methods=['POST'])
    @technician_required
    def toggle_user_status(user_id):
        user = User.query.get_or_404(user_id)
        
        if user.is_admin:
            flash('No puedes ocultar usuarios administradores.', 'danger')
            return redirect(url_for('technician_dashboard'))
        
        user.active = not user.active
        db.session.commit()
        
        status = 'activado' if user.active else 'ocultado'
        flash(f'Usuario {user.username} {status} correctamente.', 'success')
        return redirect(url_for('technician_dashboard'))

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
            
            # Verificar si esta ruta espec√≠fica est√° en progreso
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
                return jsonify({'success': False, 'message': 'Debes seleccionar un veh√≠culo'}), 400
            
            if not fuel_level or fuel_level not in [1, 2, 3, 4]:
                return jsonify({'success': False, 'message': 'Debes seleccionar el nivel de combustible (1-4)'}), 400
            
            vehicle = Vehicle.query.get(vehicle_id)
            if not vehicle or not vehicle.active:
                return jsonify({'success': False, 'message': 'El veh√≠culo seleccionado no est√° disponible'}), 400
            
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

    @app.route('/driver/navigate/<int:route_id>')
    @driver_required
    def driver_navigate(route_id):
        try:
            route = Route.query.get_or_404(route_id)
            
            # Buscar cualquier ruta en progreso del chofer (no necesariamente esta ruta espec√≠fica)
            in_progress = RouteCompletion.query.filter_by(
                driver_id=current_user.id,
                status='in_progress'
            ).first()
            
            if not in_progress:
                flash('Debes iniciar la ruta antes de navegar.', 'warning')
                return redirect(url_for('driver_view_route', route_id=route_id))
            
            # Verificar que la ruta en progreso sea la misma que se quiere navegar
            if in_progress.route_id != route_id:
                flash(f'Tienes otra ruta en progreso: {in_progress.route.name}. Compl√©tala primero.', 'warning')
                return redirect(url_for('driver_dashboard'))
            
            try:
                with open(route.file_path, 'r', encoding='utf-8') as f:
                    map_html = f.read()
            except Exception as e:
                print(f"Error cargando mapa: {e}")
                map_html = "<p>No se pudo cargar el mapa</p>"
            
            return render_template('driver/navigate.html',
                                 route=route,
                                 completion=in_progress,
                                 map_html=map_html)
        except Exception as e:
            print(f"ERROR en driver_navigate: {e}")
            flash(f'Error al cargar la navegaci√≥n: {str(e)}', 'danger')
            return redirect(url_for('driver_dashboard'))

    @app.route('/driver/update_route_progress/<int:completion_id>', methods=['POST'])
    @driver_required
    def driver_update_route_progress(completion_id):
        try:
            completion = RouteCompletion.query.get_or_404(completion_id)
            
            if completion.driver_id != current_user.id:
                return jsonify({'success': False, 'message': 'No tienes permiso para actualizar este registro'}), 403
            
            if completion.status != 'in_progress':
                return jsonify({'success': False, 'message': 'Esta ruta no est√° en progreso'}), 400
            
            data = request.json
            if not data or 'position' not in data:
                return jsonify({'success': False, 'message': 'Datos de posici√≥n requeridos'}), 400
            
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
            
            return jsonify({'success': True, 'message': 'Posici√≥n actualizada'})
            
        except Exception as e:
            print(f"ERROR en driver_update_route_progress: {e}")
            return jsonify({'success': False, 'message': f'Error al actualizar progreso: {str(e)}'}), 500

    @app.route('/driver/complete_route/<int:completion_id>', methods=['POST'])
    @driver_required
    def driver_complete_route(completion_id):
        try:
            completion = RouteCompletion.query.get_or_404(completion_id)
            
            if completion.driver_id != current_user.id:
                return jsonify({'success': False, 'message': 'No tienes permiso para actualizar este registro'}), 403
            
            if completion.status != 'in_progress':
                return jsonify({'success': False, 'message': 'Esta ruta no est√° en progreso'}), 400
            
            data = request.json
            fuel_end = data.get('fuel_level') if data else None
            notes = data.get('notes') if data else None
            
            if not fuel_end or fuel_end not in [1, 2, 3, 4]:
                return jsonify({'success': False, 'message': 'Debes seleccionar el nivel final de combustible (1-4)'}), 400
            
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
                consumption_msg = f"¬°Combustible aument√≥! (posible recarga: +{abs(completion.fuel_consumption)}/4)"
            else:
                consumption_msg = "Sin cambio en el nivel de combustible"
            
            return jsonify({
                'success': True, 
                'message': f'Ruta completada exitosamente. {consumption_msg}'
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
                return jsonify({'success': False, 'message': 'Esta ruta no est√° en progreso'}), 400
            
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
    # [Por brevedad, incluyo solo las rutas esenciales aqu√≠]

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
                return jsonify({'error': 'Tipo de reporte inv√°lido'}), 400
            
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
            
            # Agregar datos espec√≠ficos para admin
            if report_type == 'admin':
                vehicle_data = get_vehicle_performance_data()
                preview_data['vehicles'] = vehicle_data[:5]
                preview_data['summary']['total_vehicles'] = len(vehicle_data)
            
            return jsonify(preview_data)
            
        except Exception as e:
            print(f"Error en preview_report_data: {e}")
            return jsonify({'error': str(e)}), 500

    # ==================== UTILIDADES ====================
    
    

    # ==================== API PARA M√âTRICAS DE COMBUSTIBLE ====================

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
        """API para obtener posiciones de veh√≠culos activos"""
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

    # Crear tablas al inicializar la aplicaci√≥n
    


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
                cedula='000000001',  # Cambia por la c√©dula real
                role='admin'
            )
            admin.set_password('admin2024!')  # Cambia por una contrase√±a segura
        
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
        """Obtener m√©tricas de optimizaci√≥n de una ruta"""
        try:
            route = Route.query.get_or_404(route_id)
            
            if not route.gpx_path or not os.path.exists(route.gpx_path):
                return jsonify({'error': 'Archivo GPX no encontrado'}), 404
            
            optimizer = AdvancedRouteOptimizer()
            
            # Cargar puntos originales
            original_points = optimizer.load_gpx_points(route.gpx_path)
            
            # Simular optimizaci√≥n para obtener m√©tricas
            optimal_path, _ = optimizer.optimize_route_advanced([route.gpx_path], 'advanced')
            
            # Calcular m√©tricas
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
            
            # Probar importaci√≥n del optimizador
            from services.route_optimizer import AdvancedRouteOptimizer
            print("‚úì Optimizador importado correctamente")
            
            # Crear instancia
            optimizer = AdvancedRouteOptimizer()
            print("‚úì Instancia del optimizador creada")
            
            # Probar c√°lculo de distancia
            distance = optimizer.calculate_total_distance(test_points)
            print(f"‚úì Distancia total calculada: {distance} metros")
            
            # Probar detecci√≥n de bucles
            loops = optimizer.detect_loops(test_points)
            print(f"‚úì Bucles detectados: {len(loops)}")
            
            # Probar creaci√≥n de mapa
            route_map = optimizer.create_optimized_map(test_points, "Ruta de Prueba")
            print("‚úì Mapa creado correctamente")
            
            # Probar m√©tricas de validaci√≥n
            validation = optimizer.validate_optimization(test_points, test_points)
            print(f"‚úì M√©tricas de validaci√≥n: {validation}")
            
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
            print(f"ERROR de importaci√≥n: {e}")
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

    # Tambi√©n agrega esta funci√≥n para verificar directorios
    @app.route('/debug/check_directories')
    def check_directories():
        """Verificar que los directorios necesarios existen"""
        if not app.debug:
            return jsonify({'error': 'Solo disponible en modo debug'})
        
        import os
        
        directories_to_check = [
            app.config['UPLOAD_FOLDER'],
            'static',
            'static/routes',
            'services'
        ]
        
        results = {}
        
        for directory in directories_to_check:
            exists = os.path.exists(directory)
            is_writable = os.access(directory, os.W_OK) if exists else False
            
            results[directory] = {
                'exists': exists,
                'writable': is_writable,
                'absolute_path': os.path.abspath(directory)
            }
            
            if exists:
                try:
                    files = os.listdir(directory)
                    results[directory]['files_count'] = len(files)
                    results[directory]['sample_files'] = files[:5]  # Primeros 5 archivos
                except:
                    results[directory]['files_count'] = 'No accesible'
        
        return jsonify({
            'status': 'success',
            'directories': results
        })



    @app.route('/test')
    def test():
        return jsonify({
            'status': 'OK',
            'message': 'El servidor est√° funcionando correctamente',
            'timestamp': datetime.now().isoformat()
        })

    with app.app_context():
        db.create_all()
    
    return app

if __name__ == '__main__':
    app = create_app()
