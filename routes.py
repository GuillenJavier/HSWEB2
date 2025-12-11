from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import Usuario, Cita
from datetime import datetime

main = Blueprint('main', __name__)

@main.route('/')
def home():
    return render_template('home.html')

@main.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = Usuario.query.filter_by(email=email).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('main.profile'))
        
        flash('Correo o contraseña incorrectos')
    
    return render_template('login.html')

@main.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Las contraseñas no coinciden')
            return redirect(url_for('main.register'))
        
        existing_user = Usuario.query.filter_by(email=email).first()
        if existing_user:
            flash('El usuario ya existe')
            return redirect(url_for('main.register'))
        
        new_user = Usuario(email=email)
        new_user.set_password(password)
        
        db.session.add(new_user)
        db.session.commit()
        
        flash('Registro exitoso. Por favor, inicia sesión.')
        return redirect(url_for('main.login'))
    
    return render_template('register.html')

@main.route('/profile')
@login_required
def profile():
    citas = Cita.query.filter_by(usuario_id=current_user.id).all()
    return render_template('profile.html', user=current_user.email, citas=citas)

@main.route('/new-appointment', methods=['GET', 'POST'])
@login_required
def new_appointment():
    if request.method == 'POST':
        motive = request.form.get('motive')
        date = request.form.get('date')
        time = request.form.get('time')
        doctor = request.form.get('doctor')
        
        nueva_cita = Cita(
            usuario_id=current_user.id,
            motivo=motive,
            fecha=datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M"),
            doctor=doctor,
            estado='Pendiente'
        )
        
        db.session.add(nueva_cita)
        db.session.commit()
        
        flash('Cita agendada exitosamente')
        return redirect(url_for('main.profile'))
    
    return render_template('new_appointment.html')

@main.route('/view-appointments')
@login_required
def view_appointments():
    citas = Cita.query.filter_by(usuario_id=current_user.id).all()
    return render_template('view_appointments.html', citas=citas)

@main.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.home'))