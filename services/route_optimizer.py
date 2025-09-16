# Reemplaza completamente tu archivo services/route_optimizer.py con este código:

import gpxpy
import networkx as nx
from geopy.distance import geodesic
import folium
import numpy as np
from datetime import datetime
import json
import math


class AdvancedRouteOptimizer:
    """
    Optimizador mejorado que produce rutas más limpias y eficientes
    """
    
    def __init__(self):
        pass
    
    def load_gpx_points(self, file_path):
        """
        Cargar puntos desde archivo GPX
        """
        try:
            print(f"Cargando archivo GPX: {file_path}")
            
            import os
            if not os.path.exists(file_path):
                raise Exception(f"Archivo GPX no encontrado: {file_path}")
            
            with open(file_path, 'r', encoding='utf-8') as gpx_file:
                gpx = gpxpy.parse(gpx_file)
            
            points = []
            for track in gpx.tracks:
                for segment in track.segments:
                    for point in segment.points:
                        points.append((point.latitude, point.longitude))
            
            print(f"Puntos cargados: {len(points)}")
            return points
            
        except Exception as e:
            raise Exception(f"Error cargando archivo GPX {file_path}: {str(e)}")
    
    def calculate_distance(self, point1, point2):
        """
        Calcular distancia entre dos puntos en metros
        """
        return geodesic(point1, point2).meters
    
    def calculate_total_distance(self, points):
        """
        Calcular distancia total de una ruta
        """
        if len(points) < 2:
            return 0
        
        total_distance = 0
        for i in range(len(points) - 1):
            total_distance += self.calculate_distance(points[i], points[i + 1])
        
        return total_distance
    
    def clean_route_advanced(self, points, min_distance=15, angle_threshold=160):
        """
        Limpiar ruta eliminando puntos innecesarios de manera inteligente
        """
        if len(points) <= 2:
            return points
        
        print(f"Limpiando ruta: {len(points)} puntos iniciales")
        
        cleaned = [points[0]]  # Siempre mantener el primer punto
        
        i = 1
        while i < len(points) - 1:
            current = points[i]
            prev = cleaned[-1]
            
            # Si el punto está muy cerca del anterior, saltarlo
            distance_to_prev = self.calculate_distance(prev, current)
            if distance_to_prev < min_distance:
                i += 1
                continue
            
            # Verificar si este punto forma un ángulo muy agudo (posible ruido)
            if len(cleaned) >= 1 and i < len(points) - 1:
                next_point = points[i + 1]
                angle = self.calculate_angle(prev, current, next_point)
                
                # Si el ángulo es muy agudo, es posible ruido GPS
                if angle > angle_threshold:
                    i += 1
                    continue
            
            cleaned.append(current)
            i += 1
        
        # Siempre mantener el último punto
        if cleaned[-1] != points[-1]:
            cleaned.append(points[-1])
        
        print(f"Ruta limpia: {len(cleaned)} puntos ({len(points) - len(cleaned)} eliminados)")
        return cleaned
    
    def calculate_angle(self, p1, p2, p3):
        """
        Calcular ángulo entre tres puntos consecutivos en grados
        """
        # Vector de p1 a p2
        v1 = (p2[0] - p1[0], p2[1] - p1[1])
        # Vector de p2 a p3
        v2 = (p3[0] - p2[0], p3[1] - p2[1])
        
        # Producto punto
        dot_product = v1[0] * v2[0] + v1[1] * v2[1]
        
        # Magnitudes
        mag1 = math.sqrt(v1[0]**2 + v1[1]**2)
        mag2 = math.sqrt(v2[0]**2 + v2[1]**2)
        
        if mag1 == 0 or mag2 == 0:
            return 0
        
        # Coseno del ángulo
        cos_angle = dot_product / (mag1 * mag2)
        cos_angle = max(-1, min(1, cos_angle))  # Clamp entre -1 y 1
        
        # Ángulo en grados
        angle = math.degrees(math.acos(cos_angle))
        
        return angle
    
    def remove_backtracking(self, points, threshold_distance=50):
        """
        Eliminar segmentos donde el vehículo retrocede sobre la misma ruta
        """
        if len(points) <= 3:
            return points, 0
        
        print(f"Eliminando retrocesos, threshold: {threshold_distance}m")
        
        cleaned = []
        removed_segments = 0
        i = 0
        
        while i < len(points):
            current_point = points[i]
            cleaned.append(current_point)
            
            # Buscar si en los siguientes puntos regresamos cerca de donde ya estuvimos
            if len(cleaned) >= 3:
                for j in range(i + 3, min(i + 50, len(points))):  # Buscar en los próximos 50 puntos
                    future_point = points[j]
                    
                    # Comparar con puntos anteriores recientes
                    for k in range(max(0, len(cleaned) - 10), len(cleaned)):
                        past_point = cleaned[k]
                        distance = self.calculate_distance(past_point, future_point)
                        
                        if distance < threshold_distance:
                            # Encontramos un retroceso, saltar al punto futuro
                            i = j - 1  # -1 porque se incrementará al final del bucle
                            removed_segments += 1
                            print(f"Retroceso eliminado: saltando de índice {i+1} a {j}")
                            break
                    else:
                        continue
                    break
            
            i += 1
        
        print(f"Segmentos de retroceso eliminados: {removed_segments}")
        return cleaned, removed_segments
    
    def douglas_peucker_simplify(self, points, epsilon=0.0002):
        """
        Implementación del algoritmo Douglas-Peucker para simplificación de rutas
        """
        if len(points) <= 2:
            return points
        
        def perpendicular_distance(point, line_start, line_end):
            """Calcular distancia perpendicular de un punto a una línea"""
            x0, y0 = point
            x1, y1 = line_start
            x2, y2 = line_end
            
            # Si los puntos de la línea son iguales
            if x1 == x2 and y1 == y2:
                return self.calculate_distance(point, line_start) / 111000  # Convertir a grados aproximadamente
            
            # Fórmula de distancia punto-línea
            num = abs((y2 - y1) * x0 - (x2 - x1) * y0 + x2 * y1 - y2 * x1)
            den = math.sqrt((y2 - y1)**2 + (x2 - x1)**2)
            
            return num / den if den > 0 else 0
        
        def douglas_peucker_recursive(points, epsilon):
            if len(points) <= 2:
                return points
            
            # Encontrar el punto más alejado de la línea entre el primero y último
            max_distance = 0
            max_index = 0
            
            for i in range(1, len(points) - 1):
                distance = perpendicular_distance(points[i], points[0], points[-1])
                if distance > max_distance:
                    max_distance = distance
                    max_index = i
            
            # Si la distancia máxima es mayor que epsilon, dividir recursivamente
            if max_distance > epsilon:
                # Simplificar recursivamente las dos mitades
                left_half = douglas_peucker_recursive(points[:max_index + 1], epsilon)
                right_half = douglas_peucker_recursive(points[max_index:], epsilon)
                
                # Combinar resultados (eliminar punto duplicado)
                return left_half[:-1] + right_half
            else:
                # Si la distancia es pequeña, solo mantener los extremos
                return [points[0], points[-1]]
        
        simplified = douglas_peucker_recursive(points, epsilon)
        print(f"Douglas-Peucker: {len(points)} -> {len(simplified)} puntos")
        return simplified
    
    def optimize_route_advanced(self, file_paths, optimize_level='medium'):
        """
        Optimización principal con algoritmos mejorados
        """
        print(f"=== OPTIMIZACIÓN AVANZADA ===")
        print(f"Archivos: {len(file_paths)}, Nivel: {optimize_level}")
        
        # Cargar todos los puntos
        all_points = []
        for file_path in file_paths:
            try:
                points = self.load_gpx_points(file_path)
                all_points.extend(points)
            except Exception as e:
                print(f"Error cargando {file_path}: {e}")
                continue
        
        if not all_points:
            raise Exception("No se encontraron puntos GPX")
        
        print(f"Total de puntos originales: {len(all_points)}")
        original_distance = self.calculate_total_distance(all_points)
        print(f"Distancia original: {original_distance/1000:.2f} km")
        
        # Aplicar optimizaciones paso a paso
        optimized_points = all_points.copy()
        
        # 1. Limpiar puntos innecesarios
        optimized_points = self.clean_route_advanced(optimized_points)
        
        # 2. Eliminar retrocesos
        optimized_points, backtracking_removed = self.remove_backtracking(optimized_points)
        
        # 3. Simplificar con Douglas-Peucker
        if optimize_level == 'advanced':
            epsilon = 0.0001  # Más agresivo
        elif optimize_level == 'medium':
            epsilon = 0.0002
        else:
            epsilon = 0.0005  # Básico
        
        optimized_points = self.douglas_peucker_simplify(optimized_points, epsilon)
        
        # Calcular métricas finales
        final_distance = self.calculate_total_distance(optimized_points)
        
        print(f"=== RESULTADOS DE OPTIMIZACIÓN ===")
        print(f"Puntos: {len(all_points)} -> {len(optimized_points)}")
        print(f"Reducción: {len(all_points) - len(optimized_points)} puntos")
        print(f"Distancia: {original_distance/1000:.2f} -> {final_distance/1000:.2f} km")
        print(f"Retrocesos eliminados: {backtracking_removed}")
        
        return optimized_points, final_distance
    
    def validate_optimization(self, original_points, optimized_points):
        """
        Validar y calcular métricas de la optimización
        """
        original_distance = self.calculate_total_distance(original_points)
        optimized_distance = self.calculate_total_distance(optimized_points)
        
        distance_reduction = original_distance - optimized_distance
        distance_reduction_percent = (distance_reduction / original_distance * 100) if original_distance > 0 else 0
        
        points_reduction = len(original_points) - len(optimized_points)
        
        return {
            'original_points': len(original_points),
            'optimized_points': len(optimized_points),
            'points_reduction': points_reduction,
            'original_distance_km': round(original_distance / 1000, 2),
            'optimized_distance_km': round(optimized_distance / 1000, 2),
            'distance_reduction_km': round(distance_reduction / 1000, 2),
            'distance_reduction_percent': round(distance_reduction_percent, 1),
            'loops_removed': 0,  # No calculamos bucles en esta versión
            'efficiency_score': round((points_reduction / len(original_points)) * 100, 1)
        }
    
    def create_optimized_map(self, optimized_points, route_name):
        """
        Crear mapa con la ruta optimizada
        """
        if not optimized_points:
            raise Exception("No hay puntos para crear el mapa")
        
        # Calcular centro del mapa
        center_lat = sum(p[0] for p in optimized_points) / len(optimized_points)
        center_lng = sum(p[1] for p in optimized_points) / len(optimized_points)
        
        # Crear mapa
        route_map = folium.Map(
            location=[center_lat, center_lng],
            zoom_start=14,
            tiles='OpenStreetMap'
        )
        
        # Agregar ruta optimizada con mejor estilo
        folium.PolyLine(
            optimized_points,
            color='#2E8B57',  # Verde mar
            weight=5,
            opacity=0.8,
            popup=f'Ruta Optimizada: {route_name}'
        ).add_to(route_map)
        
        # Agregar marcadores de inicio y fin
        if len(optimized_points) >= 2:
            folium.Marker(
                optimized_points[0],
                popup='<b>INICIO</b><br>' + f'Lat: {optimized_points[0][0]:.6f}<br>Lng: {optimized_points[0][1]:.6f}',
                icon=folium.Icon(color='green', icon='play', prefix='fa')
            ).add_to(route_map)
            
            folium.Marker(
                optimized_points[-1],
                popup='<b>FIN</b><br>' + f'Lat: {optimized_points[-1][0]:.6f}<br>Lng: {optimized_points[-1][1]:.6f}',
                icon=folium.Icon(color='red', icon='stop', prefix='fa')
            ).add_to(route_map)
        
        # Agregar información de la ruta
        total_distance = self.calculate_total_distance(optimized_points)
        info_html = f"""
        <div style='position: fixed; 
                    top: 10px; right: 10px; width: 280px; height: 120px; 
                    background-color: rgba(255,255,255,0.9); 
                    border: 2px solid #2E8B57; border-radius: 5px; z-index:9999; 
                    font-size: 14px; padding: 15px; box-shadow: 0 2px 10px rgba(0,0,0,0.3);'>
        <h4 style='margin: 0 0 10px 0; color: #2E8B57;'>{route_name}</h4>
        <p style='margin: 5px 0;'><b>📏 Distancia:</b> {total_distance/1000:.2f} km</p>
        <p style='margin: 5px 0;'><b>📍 Puntos:</b> {len(optimized_points)}</p>
        <p style='margin: 5px 0; font-size: 12px; color: #666;'>Ruta optimizada y limpia</p>
        </div>
        """
        route_map.get_root().html.add_child(folium.Element(info_html))
        
        return route_map
    
    # Métodos de compatibilidad
    def detect_loops(self, points, tolerance=100):
        return []  # No implementado en esta versión
    
    def optimize_route_quick(self, file_paths, optimize_level='basic'):
        return self.optimize_route_advanced(file_paths, optimize_level)


# Funciones de compatibilidad
def optimize_route(file_paths):
    optimizer = AdvancedRouteOptimizer()
    return optimizer.optimize_route_advanced(file_paths, 'medium')

def load_gpx_points(file_path):
    optimizer = AdvancedRouteOptimizer()
    return optimizer.load_gpx_points(file_path)