from app import create_app, db, User, DriverInfo

def init_production_db():
    app = create_app()
    
    with app.app_context():
        # Crear todas las tablas
        db.create_all()
        
        # Crear usuario administrador inicial
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                email='admin@tuempresa.com',  # Cambiar
                first_name='Administrador',
                last_name='Principal',
                cedula='0000000001',  # Cambiar por cédula real
                role='admin'
            )
            admin.set_password('TuContraseñaSegura2024!')  # Cambiar
            
            db.session.add(admin)
            db.session.commit()
            
            print("✅ Base de datos inicializada")
            print("✅ Usuario administrador creado")
            print("👤 Usuario: admin")
            print("🔑 Contraseña: TuContraseñaSegura2024!")
            print("⚠️  CAMBIA LA CONTRASEÑA DESPUÉS DEL PRIMER LOGIN")
        else:
            print("✅ Base de datos ya existe")

if __name__ == '__main__':
    init_production_db()