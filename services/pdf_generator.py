# services/pdf_generator.py
import os
import io
import base64
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, black, white, red, green, blue
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Image
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.legends import Legend
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from io import BytesIO

class PDFReportGenerator:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.setup_custom_styles()
        
    def setup_custom_styles(self):
        """Configurar estilos personalizados"""
        # Título principal
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Title'],
            fontSize=24,
            spaceAfter=30,
            textColor=HexColor('#2c3e50'),
            alignment=TA_CENTER
        ))
        
        # Subtítulo
        self.styles.add(ParagraphStyle(
            name='Subtitle',
            parent=self.styles['Heading1'],
            fontSize=16,
            spaceAfter=12,
            textColor=HexColor('#34495e'),
            leftIndent=0
        ))
        
        # Texto de métricas
        self.styles.add(ParagraphStyle(
            name='MetricValue',
            parent=self.styles['Normal'],
            fontSize=14,
            textColor=HexColor('#27ae60'),
            alignment=TA_CENTER,
            spaceAfter=6
        ))
        
        # Texto normal mejorado
        self.styles.add(ParagraphStyle(
            name='CustomNormal',
            parent=self.styles['Normal'],
            fontSize=10,
            spaceAfter=6,
            textColor=HexColor('#2c3e50')
        ))

    def create_header(self, story, title, report_type, generated_by):
        """Crear encabezado del reporte"""
        # Logo/Título de la empresa
        company_title = Paragraph(
            "Sistema de Optimización de Rutas<br/>Yantzaza - Zamora Chinchipe", 
            self.styles['CustomTitle']
        )
        story.append(company_title)
        story.append(Spacer(1, 20))
        
        # Título del reporte
        report_title = Paragraph(title, self.styles['Subtitle'])
        story.append(report_title)
        
        # Información del reporte
        report_info = [
            ['Tipo de Reporte:', report_type],
            ['Fecha de Generación:', datetime.now().strftime('%d/%m/%Y %H:%M')],
            ['Generado por:', generated_by],
            ['Período:', 'Últimos 30 días']
        ]
        
        info_table = Table(report_info, colWidths=[2*inch, 3*inch])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), HexColor('#ecf0f1')),
            ('TEXTCOLOR', (0, 0), (-1, -1), black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 1, HexColor('#bdc3c7'))
        ]))
        
        story.append(info_table)
        story.append(Spacer(1, 30))

    def create_summary_metrics(self, story, metrics_data):
        """Crear resumen de métricas principales"""
        story.append(Paragraph("Resumen Ejecutivo", self.styles['Subtitle']))
        
        summary_data = [
            ['Métrica', 'Valor', 'Estado'],
            ['Total de Rutas', str(metrics_data.get('total_routes', 0)), 'Activo'],
            ['Rutas Completadas', str(metrics_data.get('completed_routes', 0)), 'Completado'],
            ['Rutas en Progreso', str(metrics_data.get('in_progress_routes', 0)), 'En Proceso'],
            ['Total de Choferes', str(metrics_data.get('total_drivers', 0)), 'Activo'],
            ['Total de Vehículos', str(metrics_data.get('total_vehicles', 0)), 'Disponible'],
            ['Consumo de Combustible (Mes)', f"{metrics_data.get('monthly_fuel', 0)} L", 'Normal'],
            ['Eficiencia Promedio', f"{metrics_data.get('avg_efficiency', 0)} km/L", 'Buena']
        ]
        
        summary_table = Table(summary_data, colWidths=[2.5*inch, 1.5*inch, 1.5*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#3498db')),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BACKGROUND', (0, 1), (-1, -1), HexColor('#ecf0f1')),
            ('GRID', (0, 0), (-1, -1), 1, HexColor('#bdc3c7')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f9fa')])
        ]))
        
        story.append(summary_table)
        story.append(Spacer(1, 30))

    def create_fuel_metrics_section(self, story, fuel_data):
        """Crear sección de métricas de combustible"""
        story.append(Paragraph("Análisis de Consumo de Combustible", self.styles['Subtitle']))
        
        # Métricas de combustible
        fuel_summary = [
            ['Período', 'Consumo (L)', 'Rutas', 'Eficiencia (km/L)'],
            ['Hoy', f"{fuel_data.get('today_consumption', 0)}", 
             f"{fuel_data.get('today_routes', 0)}", 
             f"{fuel_data.get('today_efficiency', 0)}"],
            ['Esta Semana', f"{fuel_data.get('week_consumption', 0)}", 
             f"{fuel_data.get('week_routes', 0)}", 
             f"{fuel_data.get('week_efficiency', 0)}"],
            ['Este Mes', f"{fuel_data.get('month_consumption', 0)}", 
             f"{fuel_data.get('month_routes', 0)}", 
             f"{fuel_data.get('month_efficiency', 0)}"]
        ]
        
        fuel_table = Table(fuel_summary, colWidths=[1.5*inch, 1.5*inch, 1.5*inch, 1.5*inch])
        fuel_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#e74c3c')),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, HexColor('#bdc3c7')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f9fa')])
        ]))
        
        story.append(fuel_table)
        story.append(Spacer(1, 20))

    def create_vehicle_performance_section(self, story, vehicle_data):
        """Crear sección de rendimiento por vehículo"""
        story.append(Paragraph("Rendimiento por Vehículo", self.styles['Subtitle']))
        
        if vehicle_data:
            vehicle_table_data = [['Vehículo', 'Placa', 'Consumo (L)', 'Rutas', 'Eficiencia']]
            
            for vehicle in vehicle_data:
                vehicle_table_data.append([
                    vehicle.get('vehicle_name', 'N/A'),
                    vehicle.get('plate', 'N/A'),
                    f"{vehicle.get('consumption', 0)}",
                    f"{vehicle.get('routes', 0)}",
                    f"{vehicle.get('efficiency', 0)} km/L"
                ])
            
            vehicle_table = Table(vehicle_table_data, colWidths=[2*inch, 1*inch, 1*inch, 1*inch, 1*inch])
            vehicle_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), HexColor('#f39c12')),
                ('TEXTCOLOR', (0, 0), (-1, 0), white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 1, HexColor('#bdc3c7')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f9fa')])
            ]))
            
            story.append(vehicle_table)
        else:
            story.append(Paragraph("No hay datos de vehículos disponibles.", self.styles['CustomNormal']))
        
        story.append(Spacer(1, 20))

    def create_driver_performance_section(self, story, driver_data):
        """Crear sección de rendimiento por chofer"""
        story.append(Paragraph("Rendimiento por Chofer", self.styles['Subtitle']))
        
        if driver_data:
            driver_table_data = [['Chofer', 'Rutas', 'Consumo (L)', 'Eficiencia', 'Puntaje']]
            
            for driver in driver_data:
                score = driver.get('score', 0)
                score_color = 'green' if score >= 85 else 'orange' if score >= 70 else 'red'
                
                driver_table_data.append([
                    driver.get('driver', 'N/A'),
                    f"{driver.get('routes', 0)}",
                    f"{driver.get('consumption', 0)}",
                    f"{driver.get('efficiency', 0)} km/L",
                    f"{score}/100"
                ])
            
            driver_table = Table(driver_table_data, colWidths=[2*inch, 1*inch, 1*inch, 1*inch, 1*inch])
            driver_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), HexColor('#27ae60')),
                ('TEXTCOLOR', (0, 0), (-1, 0), white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 1, HexColor('#bdc3c7')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f9fa')])
            ]))
            
            story.append(driver_table)
        else:
            story.append(Paragraph("No hay datos de choferes disponibles.", self.styles['CustomNormal']))
        
        story.append(Spacer(1, 20))

    def create_route_analysis_section(self, story, route_data):
        """Crear sección de análisis por ruta"""
        story.append(Paragraph("Análisis por Ruta", self.styles['Subtitle']))
        
        if route_data:
            route_table_data = [['Ruta', 'Consumo Promedio (L)', 'Completadas', 'Distancia (km)']]
            
            for route in route_data:
                distance_km = route.get('distance', 0) / 1000 if route.get('distance', 0) > 1000 else route.get('distance', 0)
                
                route_table_data.append([
                    route.get('route', 'N/A'),
                    f"{route.get('avg_consumption', 0)}",
                    f"{route.get('completions', 0)}",
                    f"{distance_km:.1f}"
                ])
            
            route_table = Table(route_table_data, colWidths=[2*inch, 1.5*inch, 1*inch, 1.5*inch])
            route_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), HexColor('#9b59b6')),
                ('TEXTCOLOR', (0, 0), (-1, 0), white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 1, HexColor('#bdc3c7')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, HexColor('#f8f9fa')])
            ]))
            
            story.append(route_table)
        else:
            story.append(Paragraph("No hay datos de rutas disponibles.", self.styles['CustomNormal']))
        
        story.append(Spacer(1, 20))

    def create_recommendations_section(self, story, metrics_data):
        """Crear sección de recomendaciones"""
        story.append(Paragraph("Recomendaciones y Observaciones", self.styles['Subtitle']))
        
        recommendations = []
        
        # Analizar eficiencia de combustible
        avg_efficiency = metrics_data.get('avg_efficiency', 0)
        if avg_efficiency < 10:
            recommendations.append("• Considerar capacitación en conducción eficiente para choferes")
            recommendations.append("• Revisar estado de mantenimiento de vehículos")
        elif avg_efficiency > 15:
            recommendations.append("• Excelente eficiencia de combustible mantenida")
        
        # Analizar uso de vehículos
        total_vehicles = metrics_data.get('total_vehicles', 0)
        in_progress = metrics_data.get('in_progress_routes', 0)
        if total_vehicles > 0:
            usage_rate = (in_progress / total_vehicles) * 100
            if usage_rate < 50:
                recommendations.append("• Considerar optimización en asignación de vehículos")
            elif usage_rate > 90:
                recommendations.append("• Alto uso de flota - considerar expansión si es necesario")
        
        # Consumo de combustible
        monthly_fuel = metrics_data.get('monthly_fuel', 0)
        if monthly_fuel > 500:  # Umbral ejemplo
            recommendations.append("• Monitorear consumo de combustible - por encima del promedio")
        
        if not recommendations:
            recommendations.append("• El sistema opera dentro de parámetros normales")
            recommendations.append("• Continuar con el monitoreo regular de métricas")
        
        for recommendation in recommendations:
            story.append(Paragraph(recommendation, self.styles['CustomNormal']))
        
        story.append(Spacer(1, 20))

    def create_footer_section(self, story):
        """Crear sección de pie de página"""
        story.append(Spacer(1, 30))
        
        footer_text = f"""
        <para align="center">
        <font size="8" color="#7f8c8d">
        Reporte generado automáticamente por el Sistema de Optimización de Rutas<br/>
        Yantzaza, Zamora Chinchipe - Ecuador<br/>
        © {datetime.now().year} - Todos los derechos reservados
        </font>
        </para>
        """
        
        story.append(Paragraph(footer_text, self.styles['CustomNormal']))

    def generate_admin_report(self, metrics_data, fuel_data, vehicle_data, driver_data, route_data, user_name):
        """Generar reporte completo para administrador"""
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
        story = []
        
        # Crear contenido del reporte
        self.create_header(story, "Reporte Administrativo Completo", "Administrador", user_name)
        self.create_summary_metrics(story, metrics_data)
        self.create_fuel_metrics_section(story, fuel_data)
        
        # Nueva página para detalles
        story.append(PageBreak())
        self.create_vehicle_performance_section(story, vehicle_data)
        self.create_driver_performance_section(story, driver_data)
        self.create_route_analysis_section(story, route_data)
        self.create_recommendations_section(story, metrics_data)
        self.create_footer_section(story)
        
        # Generar PDF
        doc.build(story)
        buffer.seek(0)
        return buffer

    def generate_coordinator_report(self, metrics_data, fuel_data, driver_data, route_data, user_name):
        """Generar reporte para coordinador"""
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5*inch, bottomMargin=0.5*inch)
        story = []
        
        # Crear contenido del reporte
        self.create_header(story, "Reporte de Coordinación", "Coordinador", user_name)
        
        # Métricas resumidas para coordinador
        coord_metrics = {
            'total_routes': metrics_data.get('total_routes', 0),
            'completed_routes': metrics_data.get('completed_routes', 0),
            'in_progress_routes': metrics_data.get('in_progress_routes', 0),
            'total_drivers': metrics_data.get('total_drivers', 0),
            'avg_efficiency': metrics_data.get('avg_efficiency', 0),
            'monthly_fuel': fuel_data.get('month_consumption', 0)
        }
        
        self.create_summary_metrics(story, coord_metrics)
        self.create_fuel_metrics_section(story, fuel_data)
        self.create_driver_performance_section(story, driver_data)
        self.create_route_analysis_section(story, route_data)
        self.create_recommendations_section(story, coord_metrics)
        self.create_footer_section(story)
        
        # Generar PDF
        doc.build(story)
        buffer.seek(0)
        return buffer