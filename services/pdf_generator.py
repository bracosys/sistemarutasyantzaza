# services/pdf_generator.py

import io
from datetime import datetime
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from reportlab.platypus.flowables import HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

class PDFReportGenerator:
    def __init__(self):
        self.styles = getSampleStyleSheet()
        self.setup_custom_styles()
    
    def setup_custom_styles(self):
        """Configurar estilos personalizados"""
        # Estilo para títulos principales
        self.styles.add(ParagraphStyle(
            name='MainTitle',
            parent=self.styles['Heading1'],
            fontSize=18,
            textColor=colors.darkblue,
            alignment=TA_CENTER,
            spaceAfter=20
        ))
        
        # Estilo para subtítulos
        self.styles.add(ParagraphStyle(
            name='SectionTitle',
            parent=self.styles['Heading2'],
            fontSize=14,
            textColor=colors.darkgreen,
            spaceBefore=15,
            spaceAfter=10
        ))
        
        # Estilo para texto destacado
        self.styles.add(ParagraphStyle(
            name='Highlight',
            parent=self.styles['Normal'],
            fontSize=12,
            textColor=colors.darkblue,
            fontName='Helvetica-Bold'
        ))
        
        # Estilo para métricas
        self.styles.add(ParagraphStyle(
            name='Metric',
            parent=self.styles['Normal'],
            fontSize=11,
            alignment=TA_CENTER,
            textColor=colors.darkred
        ))
    
    def generate_admin_report_with_optimization(self, data, user_name):
        """Generar reporte administrativo completo con métricas de optimización"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18
        )
        
        story = []
        
        # Encabezado del reporte
        story.append(Paragraph("REPORTE ADMINISTRATIVO COMPLETO", self.styles['MainTitle']))
        story.append(Paragraph("Sistema de Optimización de Rutas - Yantzaza", self.styles['Heading3']))
        story.append(Spacer(1, 20))
        
        # Información del reporte
        report_info = [
            ['Generado por:', user_name],
            ['Fecha:', datetime.now().strftime('%d/%m/%Y %H:%M')],
            ['Período:', 'Últimos 30 días'],
            ['Tipo:', 'Reporte Administrativo Completo con Optimizaciones']
        ]
        
        info_table = Table(report_info, colWidths=[2*inch, 3*inch])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(info_table)
        story.append(Spacer(1, 20))
        
        # SECCIÓN 1: RESUMEN EJECUTIVO
        story.append(Paragraph("1. RESUMEN EJECUTIVO", self.styles['SectionTitle']))
        
        metrics = data.get('metrics', {})
        optimization = data.get('optimization', {})
        
        # Métricas generales
        general_metrics = [
            ['Métrica', 'Valor', 'Optimización'],
            ['Total Usuarios', str(metrics.get('total_users', 0)), '-'],
            ['Total Choferes', str(metrics.get('total_drivers', 0)), '-'],
            ['Total Vehículos', str(metrics.get('total_vehicles', 0)), '-'],
            ['Total Rutas', str(metrics.get('total_routes', 0)), f"{optimization.get('total_routes_optimized', 0)} optimizadas"],
            ['Rutas Completadas', str(metrics.get('completed_routes', 0)), '-'],
            ['Rutas en Progreso', str(metrics.get('in_progress_routes', 0)), '-']
        ]
        
        metrics_table = Table(general_metrics, colWidths=[2*inch, 1*inch, 2*inch])
        metrics_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige)
        ]))
        story.append(metrics_table)
        story.append(Spacer(1, 15))
        
        # SECCIÓN 2: MÉTRICAS DE OPTIMIZACIÓN (NUEVA)
        story.append(Paragraph("2. MÉTRICAS DE OPTIMIZACIÓN DE RUTAS", self.styles['SectionTitle']))
        
        if optimization and optimization.get('total_routes_optimized', 0) > 0:
            optimization_metrics = [
                ['Indicador', 'Valor', 'Impacto'],
                ['Rutas Optimizadas', str(optimization.get('total_routes_optimized', 0)), 'Alto'],
                ['Kilómetros Ahorrados', f"{optimization.get('total_km_saved', 0)} km", 'Muy Alto'],
                ['Tiempo Ahorrado', f"{optimization.get('total_time_saved_minutes', 0)} minutos", 'Alto'],
                ['Combustible Ahorrado', f"{optimization.get('total_fuel_saved_liters', 0)} litros", 'Muy Alto'],
                ['Mejora Promedio', f"{optimization.get('average_improvement_percent', 0)}%", 'Excelente']
            ]
            
            # Calcular ahorro económico mensual estimado
            monthly_fuel_savings = optimization.get('total_fuel_saved_liters', 0) * 1.2  # $1.2 por litro
            monthly_time_value = (optimization.get('total_time_saved_minutes', 0) / 60) * 20  # $20/hora
            monthly_maintenance = optimization.get('total_km_saved', 0) * 0.5  # $0.5/km
            total_monthly_savings = monthly_fuel_savings + monthly_time_value + monthly_maintenance
            
            optimization_metrics.append(['Ahorro Mensual Estimado', f"${total_monthly_savings:.2f}", 'Crítico'])
            optimization_metrics.append(['Proyección Anual', f"${total_monthly_savings * 12:.2f}", 'Estratégico'])
            
            optimization_table = Table(optimization_metrics, colWidths=[2.2*inch, 1.5*inch, 1.3*inch])
            optimization_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 1), (-1, -1), colors.lightgreen),
                # Resaltar filas de ahorro económico
                ('BACKGROUND', (0, -2), (-1, -1), colors.lightyellow),
                ('TEXTCOLOR', (0, -2), (-1, -1), colors.darkred),
                ('FONTNAME', (0, -2), (-1, -1), 'Helvetica-Bold')
            ]))
            story.append(optimization_table)
            
            # Mejor optimización
            if optimization.get('best_optimization'):
                best = optimization['best_optimization']
                story.append(Spacer(1, 10))
                story.append(Paragraph(f"<b>Mejor Optimización:</b> {best['route_name']} - {best['improvement']}% de mejora ({best['km_saved']} km ahorrados)", self.styles['Highlight']))
        else:
            story.append(Paragraph("No se han registrado optimizaciones de rutas aún.", self.styles['Normal']))
            story.append(Paragraph("Recomendación: Implementar optimización en rutas nuevas para obtener beneficios económicos significativos.", self.styles['Highlight']))
        
        story.append(Spacer(1, 20))
        
        # SECCIÓN 3: CONSUMO DE COMBUSTIBLE
        story.append(Paragraph("3. ANÁLISIS DE CONSUMO DE COMBUSTIBLE", self.styles['SectionTitle']))
        
        fuel = data.get('fuel', {})
        fuel_data = [
            ['Período', 'Consumo (L)', 'Rutas', 'Eficiencia (km/L)'],
            ['Hoy', str(fuel.get('today_consumption', 0)), str(fuel.get('today_routes', 0)), str(fuel.get('today_efficiency', 0))],
            ['Esta Semana', str(fuel.get('week_consumption', 0)), str(fuel.get('week_routes', 0)), str(fuel.get('week_efficiency', 0))],
            ['Este Mes', str(fuel.get('month_consumption', 0)), str(fuel.get('month_routes', 0)), str(fuel.get('month_efficiency', 0))]
        ]
        
        fuel_table = Table(fuel_data, colWidths=[1.5*inch, 1.2*inch, 1*inch, 1.3*inch])
        fuel_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.orange),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 1), (-1, -1), colors.lightyellow)
        ]))
        story.append(fuel_table)
        story.append(Spacer(1, 15))
        
        # SECCIÓN 4: RENDIMIENTO POR VEHÍCULO
        story.append(Paragraph("4. RENDIMIENTO POR VEHÍCULO", self.styles['SectionTitle']))
        
        vehicles = data.get('vehicles', [])
        if vehicles:
            vehicle_data = [['Vehículo', 'Placa', 'Consumo (L)', 'Rutas', 'Eficiencia']]
            for vehicle in vehicles[:10]:  # Top 10
                vehicle_data.append([
                    vehicle.get('vehicle_name', 'N/A'),
                    vehicle.get('plate', 'N/A'),
                    str(vehicle.get('consumption', 0)),
                    str(vehicle.get('routes', 0)),
                    f"{vehicle.get('efficiency', 0)} km/L"
                ])
            
            vehicle_table = Table(vehicle_data, colWidths=[1.8*inch, 1*inch, 1*inch, 0.8*inch, 1.4*inch])
            vehicle_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.blue),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 1), (-1, -1), colors.lightblue)
            ]))
            story.append(vehicle_table)
        else:
            story.append(Paragraph("No hay datos de vehículos disponibles.", self.styles['Normal']))
        
        story.append(PageBreak())
        
        # SECCIÓN 5: RENDIMIENTO POR CONDUCTOR
        story.append(Paragraph("5. RENDIMIENTO POR CONDUCTOR", self.styles['SectionTitle']))
        
        drivers = data.get('drivers', [])
        if drivers:
            driver_data = [['Conductor', 'Consumo (L)', 'Rutas', 'Eficiencia', 'Puntuación']]
            for driver in drivers[:10]:  # Top 10
                driver_data.append([
                    driver.get('driver', 'N/A'),
                    str(driver.get('consumption', 0)),
                    str(driver.get('routes', 0)),
                    f"{driver.get('efficiency', 0)} km/L",
                    str(driver.get('score', 0))
                ])
            
            driver_table = Table(driver_data, colWidths=[2*inch, 1*inch, 0.8*inch, 1.2*inch, 1*inch])
            driver_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.purple),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 1), (-1, -1), colors.lavender)
            ]))
            story.append(driver_table)
        else:
            story.append(Paragraph("No hay datos de conductores disponibles.", self.styles['Normal']))
        
        story.append(Spacer(1, 15))
        
        # SECCIÓN 6: ANÁLISIS DE RUTAS
        story.append(Paragraph("6. ANÁLISIS DE RUTAS", self.styles['SectionTitle']))
        
        routes = data.get('routes', [])
        optimized_routes = data.get('optimized_routes', {}).get('routes', [])
        
        if routes:
            route_data = [['Ruta', 'Consumo Promedio (L)', 'Completadas', 'Optimizada', 'Ahorro (km)']]
            
            # Crear un diccionario para búsqueda rápida de rutas optimizadas
            optimized_dict = {route.id: route for route in optimized_routes if hasattr(route, 'id')}
            
            for route in routes[:10]:  # Top 10
                route_name = route.get('route', 'N/A')
                avg_consumption = str(route.get('avg_consumption', 0))
                completions = str(route.get('completions', 0))
                
                # Verificar si la ruta está optimizada (esto es una aproximación)
                is_optimized = "No"
                km_saved = "0"
                
                # Si tenemos datos de rutas optimizadas, buscar coincidencias por nombre
                for opt_route in optimized_routes:
                    if hasattr(opt_route, 'name') and opt_route.name == route_name:
                        is_optimized = "Sí"
                        km_saved = f"{getattr(opt_route, 'distance_saved_km', 0):.1f}"
                        break
                
                route_data.append([route_name, avg_consumption, completions, is_optimized, km_saved])
            
            route_table = Table(route_data, colWidths=[2*inch, 1.2*inch, 1*inch, 1*inch, 0.8*inch])
            route_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkred),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 1), (-1, -1), colors.mistyrose)
            ]))
            story.append(route_table)
        else:
            story.append(Paragraph("No hay datos de rutas disponibles.", self.styles['Normal']))
        
        story.append(Spacer(1, 20))
        
        # SECCIÓN 7: RECOMENDACIONES Y CONCLUSIONES
        story.append(Paragraph("7. RECOMENDACIONES Y CONCLUSIONES", self.styles['SectionTitle']))
        
        # Generar recomendaciones basadas en los datos
        recommendations = []
        
        # Recomendaciones de optimización
        if optimization.get('total_routes_optimized', 0) == 0:
            recommendations.append("• CRÍTICO: Implementar optimización de rutas inmediatamente. Potencial de ahorro significativo.")
        elif optimization.get('total_routes_optimized', 0) < metrics.get('total_routes', 0):
            remaining = metrics.get('total_routes', 0) - optimization.get('total_routes_optimized', 0)
            recommendations.append(f"• Aplicar optimización a las {remaining} rutas restantes para maximizar ahorros.")
        
        if optimization.get('average_improvement_percent', 0) > 10:
            recommendations.append("• Excelente: Las optimizaciones están generando ahorros significativos (>10%).")
        elif optimization.get('average_improvement_percent', 0) > 5:
            recommendations.append("• Bueno: Las optimizaciones muestran mejoras moderadas. Considerar técnicas avanzadas.")
        
        # Recomendaciones de combustible
        if fuel.get('month_efficiency', 0) < 10:
            recommendations.append("• Implementar programa de capacitación en conducción eficiente.")
        
        # Recomendaciones de vehículos
        if vehicles:
            low_efficiency_vehicles = [v for v in vehicles if v.get('efficiency', 0) < 8]
            if low_efficiency_vehicles:
                recommendations.append(f"• Evaluar mantenimiento de {len(low_efficiency_vehicles)} vehículos con baja eficiencia.")
        
        # Recomendaciones económicas
        if optimization.get('total_fuel_saved_liters', 0) > 50:
            monthly_savings = optimization.get('total_fuel_saved_liters', 0) * 1.2
            recommendations.append(f"• Excelente ROI: Ahorros mensuales estimados de ${monthly_savings:.2f} en combustible.")
        
        if not recommendations:
            recommendations.append("• Continuar monitoreando métricas y implementar optimizaciones graduales.")
        
        for rec in recommendations:
            story.append(Paragraph(rec, self.styles['Normal']))
        
        story.append(Spacer(1, 15))
        
        # Conclusión final
        conclusion_text = f"""
        <b>CONCLUSIÓN EJECUTIVA:</b><br/>
        El sistema de optimización de rutas de Yantzaza ha procesado {metrics.get('total_routes', 0)} rutas totales, 
        con {optimization.get('total_routes_optimized', 0)} rutas optimizadas que han generado ahorros de 
        {optimization.get('total_km_saved', 0)} km y {optimization.get('total_fuel_saved_liters', 0)} litros de combustible.
        <br/><br/>
        El impacto económico mensual estimado es de ${(optimization.get('total_fuel_saved_liters', 0) * 1.2 + 
        (optimization.get('total_time_saved_minutes', 0) / 60) * 20 + 
        optimization.get('total_km_saved', 0) * 0.5):.2f}, 
        con una proyección anual de ${((optimization.get('total_fuel_saved_liters', 0) * 1.2 + 
        (optimization.get('total_time_saved_minutes', 0) / 60) * 20 + 
        optimization.get('total_km_saved', 0) * 0.5) * 12):.2f}.
        """
        
        story.append(Paragraph(conclusion_text, self.styles['Highlight']))
        
        # Separador final
        story.append(Spacer(1, 20))
        story.append(HRFlowable(width="100%", thickness=2, color=colors.darkblue))
        story.append(Spacer(1, 10))
        story.append(Paragraph("Reporte generado automáticamente por el Sistema de Optimización de Rutas", 
                              self.styles['Normal']))
        story.append(Paragraph(f"Fecha y hora: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", 
                              self.styles['Normal']))
        
        # Construir PDF
        doc.build(story)
        buffer.seek(0)
        
        return buffer
    
    def generate_coordinator_report(self, metrics_data, fuel_data, driver_data, route_data, user_name):
        """Generar reporte de coordinador (versión simplificada)"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18
        )
        
        story = []
        
        # Encabezado del reporte
        story.append(Paragraph("REPORTE DE COORDINACIÓN", self.styles['MainTitle']))
        story.append(Paragraph("Sistema de Optimización de Rutas - Yantzaza", self.styles['Heading3']))
        story.append(Spacer(1, 20))
        
        # Información del reporte
        report_info = [
            ['Generado por:', user_name],
            ['Fecha:', datetime.now().strftime('%d/%m/%Y %H:%M')],
            ['Período:', 'Últimos 30 días'],
            ['Tipo:', 'Reporte de Coordinación']
        ]
        
        info_table = Table(report_info, colWidths=[2*inch, 3*inch])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(info_table)
        story.append(Spacer(1, 20))
        
        # Resumen de operaciones
        story.append(Paragraph("1. RESUMEN OPERATIVO", self.styles['SectionTitle']))
        
        operational_data = [
            ['Métrica', 'Valor'],
            ['Rutas Completadas', str(metrics_data.get('completed_routes', 0))],
            ['Rutas en Progreso', str(metrics_data.get('in_progress_routes', 0))],
            ['Conductores Activos', str(metrics_data.get('total_drivers', 0))],
            ['Eficiencia Promedio', f"{metrics_data.get('avg_efficiency', 0)} km/L"]
        ]
        
        operational_table = Table(operational_data, colWidths=[3*inch, 2*inch])
        operational_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige)
        ]))
        story.append(operational_table)
        story.append(Spacer(1, 20))
        
        # Top conductores
        story.append(Paragraph("2. RENDIMIENTO DE CONDUCTORES", self.styles['SectionTitle']))
        
        if driver_data:
            driver_performance = [['Conductor', 'Rutas', 'Eficiencia', 'Puntuación']]
            for driver in driver_data[:5]:  # Top 5
                driver_performance.append([
                    driver.get('driver', 'N/A'),
                    str(driver.get('routes', 0)),
                    f"{driver.get('efficiency', 0)} km/L",
                    str(driver.get('score', 0))
                ])
            
            driver_table = Table(driver_performance, colWidths=[2.5*inch, 1*inch, 1.25*inch, 1.25*inch])
            driver_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 1), (-1, -1), colors.lightgreen)
            ]))
            story.append(driver_table)
        
        story.append(Spacer(1, 20))
        
        # Consumo de combustible
        story.append(Paragraph("3. CONSUMO DE COMBUSTIBLE", self.styles['SectionTitle']))
        
        fuel_summary = [
            ['Período', 'Consumo (L)', 'Rutas', 'Eficiencia'],
            ['Hoy', str(fuel_data.get('today_consumption', 0)), str(fuel_data.get('today_routes', 0)), str(fuel_data.get('today_efficiency', 0))],
            ['Esta Semana', str(fuel_data.get('week_consumption', 0)), str(fuel_data.get('week_routes', 0)), str(fuel_data.get('week_efficiency', 0))],
            ['Este Mes', str(fuel_data.get('month_consumption', 0)), str(fuel_data.get('month_routes', 0)), str(fuel_data.get('month_efficiency', 0))]
        ]
        
        fuel_table = Table(fuel_summary, colWidths=[1.5*inch, 1.2*inch, 1*inch, 1.3*inch])
        fuel_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.orange),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 1), (-1, -1), colors.lightyellow)
        ]))
        story.append(fuel_table)
        
        # Construir PDF
        doc.build(story)
        buffer.seek(0)
        
        return buffer