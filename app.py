# --- bootstrap path for PyInstaller onefile (import local modules) ---
import os, sys
if getattr(sys, "frozen", False):
    # Ejecutable: asegura que Python vea el paquete extraído por PyInstaller
    sys.path.insert(0, os.path.dirname(sys.executable))
    if hasattr(sys, "_MEIPASS"):
        sys.path.insert(0, sys._MEIPASS)
else:
    # Ejecución normal: carpeta del proyecto
    sys.path.insert(0, os.path.dirname(__file__))
# --- end bootstrap ---


from datetime import datetime, time, timedelta
from contextlib import contextmanager
import os, secrets

from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.orm import joinedload
from sqlalchemy import func

from database import SessionLocal, init_db
from models import Usuario, Medico, Cita, TipoUsuario, EstadoCita, Expediente
from utils import has_overlap

# ----------------- APP & LOGIN -----------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", secrets.token_hex(32))

init_db()

login_manager = LoginManager()
login_manager.login_view = "login"  # endpoint al que redirige si no estás autenticado
login_manager.init_app(app)

@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

@login_manager.user_loader
def load_user(user_id):
    with get_db() as db:
        return db.get(Usuario, int(user_id))


# ----------------- HELPERS -----------------
def saludo_actual():
    h = datetime.now().hour
    if 5 <= h <= 11:
        return "Buen día"
    elif 12 <= h <= 18:
        return "Buenas tardes"
    return "Buenas noches"


# ----------------- DASHBOARD -----------------
@app.route("/")
@login_required
def dashboard():
    saludo = None
    doctor_nombre = None
    pacientes = []
    pending_counts = {}

    with get_db() as db:
        medico = None
        if current_user.tipo == TipoUsuario.MEDICO:
            medico = (
                db.query(Medico)
                .options(joinedload(Medico.usuario))
                .filter(Medico.usuario_id == current_user.id)
                .first()
            )
            if medico and medico.usuario:
                saludo = saludo_actual()
                doctor_nombre = f"Dr. {medico.usuario.nombre} {medico.usuario.apellido}"

            if medico:
                # Pacientes únicos que han tenido citas con este médico
                pacientes = (
                    db.query(Usuario)
                    .join(Cita, Cita.paciente_id == Usuario.id)
                    .filter(Cita.medico_id == medico.id)
                    .distinct()
                    .order_by(Usuario.apellido.asc(), Usuario.nombre.asc())
                    .all()
                )
                # Conteo de citas pendientes por paciente
                ahora = datetime.now()
                rows = (
                    db.query(Cita.paciente_id, func.count(Cita.id))
                    .filter(
                        Cita.medico_id == medico.id,
                        Cita.start_at >= ahora,
                        Cita.estado.in_([EstadoCita.PENDIENTE, EstadoCita.CONFIRMADA]),
                    )
                    .group_by(Cita.paciente_id)
                    .all()
                )
                pending_counts = {pid: cnt for (pid, cnt) in rows}

        base_query = db.query(Cita).options(
            joinedload(Cita.medico).joinedload(Medico.usuario),
            joinedload(Cita.paciente),
        )
        if current_user.tipo == TipoUsuario.MEDICO and medico:
            citas = base_query.filter(Cita.medico_id == medico.id).order_by(Cita.start_at.desc()).all()
        elif current_user.tipo == TipoUsuario.PACIENTE:
            citas = base_query.filter(Cita.paciente_id == current_user.id).order_by(Cita.start_at.desc()).all()
        else:
            citas = base_query.order_by(Cita.start_at.desc()).all()

    return render_template(
        "dashboard.html",
        citas=citas,
        TipoUsuario=TipoUsuario,
        EstadoCita=EstadoCita,
        saludo=saludo,
        doctor_nombre=doctor_nombre,
        pacientes=pacientes,
        pending_counts=pending_counts
    )


# ----------------- AUTH -----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        nombre = request.form["nombre"].strip()
        apellido = request.form["apellido"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        tipo = request.form.get("tipo", "PACIENTE")
        especialidad = request.form.get("especialidad", "").strip()

        with get_db() as db:
            if db.query(Usuario).filter_by(email=email).first():
                flash("El correo ya está registrado", "warning")
                return redirect(url_for("register"))

            u = Usuario(
                nombre=nombre,
                apellido=apellido,
                email=email,
                password_hash=generate_password_hash(password),
                tipo=TipoUsuario(tipo),
            )
            db.add(u)
            db.flush()

            if u.tipo == TipoUsuario.MEDICO:
                if not especialidad:
                    flash("Debes indicar la especialidad del médico", "warning")
                    return redirect(url_for("register"))
                m = Medico(usuario_id=u.id, especialidad=especialidad)
                db.add(m)

        flash("Registro exitoso. Inicia sesión.", "success")
        return redirect(url_for("login"))
    return render_template("register.html", TipoUsuario=TipoUsuario)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        with get_db() as db:
            u = db.query(Usuario).filter_by(email=email).first()
            if not u or not check_password_hash(u.password_hash, password):
                flash("Credenciales inválidas", "danger")
                return redirect(url_for("login"))

            login_user(u)
            next_url = request.args.get("next")
            return redirect(next_url or url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ----------------- CITAS -----------------
@app.route("/citas")
@login_required
def citas_list():
    with get_db() as db:
        medico = None
        if current_user.tipo == TipoUsuario.MEDICO:
            medico = db.query(Medico).filter(Medico.usuario_id == current_user.id).first()

        base_query = db.query(Cita).options(
            joinedload(Cita.medico).joinedload(Medico.usuario),
            joinedload(Cita.paciente),
        )
        if current_user.tipo == TipoUsuario.MEDICO and medico:
            citas = base_query.filter(Cita.medico_id == medico.id).order_by(Cita.start_at.desc()).all()
        elif current_user.tipo == TipoUsuario.PACIENTE:
            citas = base_query.filter(Cita.paciente_id == current_user.id).order_by(Cita.start_at.desc()).all()
        else:
            citas = base_query.order_by(Cita.start_at.desc()).all()

        medicos = db.query(Medico).options(joinedload(Medico.usuario)).all()

    return render_template("appointments_list.html", citas=citas, medicos=medicos, EstadoCita=EstadoCita)


@app.route("/citas/nueva", methods=["GET", "POST"])
@login_required
def appointments_new():
    # Si el doctor viene desde "Agendar cita" para un paciente: ?paciente_id=
    selected_paciente_id = request.args.get("paciente_id", type=int)

    with get_db() as db:
        medicos = db.query(Medico).options(joinedload(Medico.usuario)).all()
        selected_paciente = db.get(Usuario, selected_paciente_id) if selected_paciente_id else None

    if request.method == "POST":
        try:
            medico_id = int(request.form["medico_id"])
            start_at = datetime.fromisoformat(request.form["start_at"])
            end_at = datetime.fromisoformat(request.form["end_at"])
        except Exception:
            flash("Datos de fecha/hora inválidos.", "warning")
            return redirect(
                url_for("appointments_new", paciente_id=selected_paciente_id)
                if selected_paciente_id else url_for("appointments_new")
            )

        notas = request.form.get("notas") or None

        if end_at <= start_at:
            flash("La hora de fin debe ser posterior al inicio", "warning")
            return redirect(
                url_for("appointments_new", paciente_id=selected_paciente_id)
                if selected_paciente_id else url_for("appointments_new")
            )

        # ¿Para quién es la cita?
        paciente_id = current_user.id
        if current_user.tipo == TipoUsuario.MEDICO:
            form_pid = request.form.get("paciente_id", type=int)
            if form_pid:
                paciente_id = form_pid

        with get_db() as db:
            if current_user.tipo == TipoUsuario.MEDICO and not db.get(Usuario, paciente_id):
                flash("Paciente no encontrado.", "warning")
                return redirect(url_for("appointments_new"))

            if has_overlap(db, medico_id, start_at, end_at):
                flash("El médico ya tiene una cita en ese horario", "warning")
                return redirect(
                    url_for("appointments_new", paciente_id=selected_paciente_id)
                    if selected_paciente_id else url_for("appointments_new")
                )

            cita = Cita(
                medico_id=medico_id,
                paciente_id=paciente_id,
                start_at=start_at,
                end_at=end_at,
                estado=EstadoCita.PENDIENTE,
                notas=notas,
            )
            db.add(cita)

        flash("Cita creada", "success")
        return redirect(url_for("citas_list"))

    return render_template("appointments_new.html", medicos=medicos, selected_paciente=selected_paciente)



@app.route("/citas/<int:cita_id>/editar", methods=["GET", "POST"])
@login_required
def citas_edit(cita_id: int):
    # GET con eager loading
    with get_db() as db:
        cita = (
            db.query(Cita)
            .options(
                joinedload(Cita.medico).joinedload(Medico.usuario),
                joinedload(Cita.paciente),
            )
            .filter(Cita.id == cita_id)
            .first()
        )
        if not cita:
            flash("Cita no encontrada", "warning")
            return redirect(url_for("citas_list"))

        medicos = db.query(Medico).options(joinedload(Medico.usuario)).all()
        medico_actual = None
        if current_user.tipo == TipoUsuario.MEDICO:
            medico_actual = db.query(Medico).filter(Medico.usuario_id == current_user.id).first()

    # permisos para ver/editar
    puede_ver = (
        current_user.tipo == TipoUsuario.ADMIN
        or (current_user.tipo == TipoUsuario.PACIENTE and current_user.id == cita.paciente_id)
        or (current_user.tipo == TipoUsuario.MEDICO and medico_actual and medico_actual.id == cita.medico_id)
    )
    if not puede_ver:
        flash("No tienes permisos para editar esta cita", "danger")
        return redirect(url_for("citas_list"))

    if request.method == "POST":
        try:
            start_at = datetime.fromisoformat(request.form["start_at"])
            end_at = datetime.fromisoformat(request.form["end_at"])
        except Exception:
            flash("Formato de fecha/hora inválido.", "warning")
            return redirect(url_for("citas_edit", cita_id=cita_id))

        if end_at <= start_at:
            flash("La hora de fin debe ser posterior al inicio", "warning")
            return redirect(url_for("citas_edit", cita_id=cita_id))

        with get_db() as db:
            c = db.get(Cita, cita_id)
            if not c:
                flash("Cita no encontrada", "warning")
                return redirect(url_for("citas_list"))

            target_medico_id = c.medico_id

            # Admin y Médico pueden modificar todo
            if current_user.tipo in (TipoUsuario.ADMIN, TipoUsuario.MEDICO):
                if "medico_id" in request.form:
                    try:
                        target_medico_id = int(request.form["medico_id"])
                    except Exception:
                        flash("ID de médico inválido.", "warning")
                        return redirect(url_for("citas_edit", cita_id=cita_id))

                if "paciente_id" in request.form:
                    try:
                        nuevo_paciente_id = int(request.form["paciente_id"])
                        c.paciente_id = nuevo_paciente_id
                    except Exception:
                        flash("ID de paciente inválido.", "warning")
                        return redirect(url_for("citas_edit", cita_id=cita_id))

                estado_val = request.form.get(
                    "estado",
                    c.estado.value if c.estado else EstadoCita.PENDIENTE.value
                )
                c.estado = EstadoCita(estado_val)
                c.notas = request.form.get("notas") or None
            # Paciente: solo fechas (ya tomadas arriba)

            if has_overlap(db, target_medico_id, start_at, end_at, exclude_id=c.id):
                flash("El médico ya tiene una cita en ese horario", "warning")
                return redirect(url_for("citas_edit", cita_id=cita_id))

            c.medico_id = target_medico_id
            c.start_at = start_at
            c.end_at = end_at

        flash("Cita actualizada", "success")
        return redirect(url_for("citas_list"))

    es_admin = current_user.tipo == TipoUsuario.ADMIN
    es_medico_prop = current_user.tipo == TipoUsuario.MEDICO and medico_actual and medico_actual.id == cita.medico_id
    puede_editar_todo = es_admin or es_medico_prop

    return render_template(
        "appointments_edit.html",
        cita=cita,
        medicos=medicos,
        EstadoCita=EstadoCita,
        puede_editar_todo=puede_editar_todo
    )


@app.route("/citas/<int:cita_id>/cancelar", methods=["POST"])
@login_required
def citas_cancel(cita_id: int):
    """Cancela una cita.
    - Paciente: solo si faltan >= 24h.
    - Médico/Admin: pueden cancelar en cualquier momento.
    """
    from datetime import datetime, timedelta

    with get_db() as db:
        c = db.get(Cita, cita_id)
        if not c:
            flash("Cita no encontrada.", "warning")
            return redirect(url_for("citas_list"))

        # ¿Quién es el médico actual (si aplica)?
        medico_actual = None
        if current_user.tipo == TipoUsuario.MEDICO:
            medico_actual = db.query(Medico).filter(Medico.usuario_id == current_user.id).first()

        # Permisos
        permitido = (
            current_user.tipo == TipoUsuario.ADMIN
            or (current_user.tipo == TipoUsuario.PACIENTE and current_user.id == c.paciente_id)
            or (current_user.tipo == TipoUsuario.MEDICO and medico_actual and medico_actual.id == c.medico_id)
        )
        if not permitido:
            flash("No tienes permisos para cancelar esta cita.", "danger")
            return redirect(url_for("citas_list"))

        # Regla de 24h para PACIENTE
        if current_user.tipo == TipoUsuario.PACIENTE:
            ahora = datetime.now()
            if (c.start_at - ahora) < timedelta(hours=24):
                flash("Solo puedes cancelar con al menos 24 horas de anticipación.", "warning")
                return redirect(url_for("citas_list"))

        # Ya estaba cancelada
        if c.estado == EstadoCita.CANCELADA:
            flash("La cita ya estaba cancelada.", "info")
            return redirect(url_for("citas_list"))

        c.estado = EstadoCita.CANCELADA
        flash("Cita cancelada correctamente.", "success")
        return redirect(url_for("citas_list"))


# ----------------------------------------------
# Cita nueva (flujo específico para DOCTOR)
# ----------------------------------------------
@app.route("/doctor/citas/nueva", methods=["GET", "POST"])
@login_required
def doctor_appointments_new():
    if current_user.tipo not in (TipoUsuario.MEDICO, TipoUsuario.ADMIN):
        abort(403)

    with get_db() as db:
        # Lista de médicos (por si admin agenda para cualquiera)
        medicos = db.query(Medico).options(joinedload(Medico.usuario)).all()

        # Determina el médico actual (si es médico)
        medico_actual = None
        if current_user.tipo == TipoUsuario.MEDICO:
            medico_actual = (
                db.query(Medico)
                .filter(Medico.usuario_id == current_user.id)
                .first()
            )

        # Lista de pacientes (solo usuarios tipo PACIENTE)
        pacientes = (
            db.query(Usuario)
            .filter(Usuario.tipo == TipoUsuario.PACIENTE)
            .order_by(Usuario.apellido.asc(), Usuario.nombre.asc())
            .all()
        )

    if request.method == "POST":
        try:
            paciente_id = int(request.form["paciente_id"])
            medico_id = int(request.form["medico_id"])
            start_at = datetime.fromisoformat(request.form["start_at"])
            end_at = datetime.fromisoformat(request.form["end_at"])
        except Exception:
            flash("Revisa que seleccionaste paciente, médico y las fechas/horas tengan formato válido.", "warning")
            return redirect(url_for("doctor_appointments_new"))

        notas = request.form.get("notas") or None

        if end_at <= start_at:
            flash("La hora de fin debe ser posterior al inicio.", "warning")
            return redirect(url_for("doctor_appointments_new"))

        with get_db() as db:
            # Valida que el paciente exista
            if not db.get(Usuario, paciente_id):
                flash("Paciente no encontrado.", "warning")
                return redirect(url_for("doctor_appointments_new"))

            # Si es médico, solo puede agendar con su propio ID (a menos que sea admin)
            if current_user.tipo == TipoUsuario.MEDICO:
                medico_actual = (
                    db.query(Medico).filter(Medico.usuario_id == current_user.id).first()
                )
                if not medico_actual or medico_actual.id != medico_id:
                    flash("No puedes agendar citas para otro médico.", "danger")
                    return redirect(url_for("doctor_appointments_new"))

            # Valida traslape
            if has_overlap(db, medico_id, start_at, end_at):
                flash("El médico ya tiene una cita que se traslapa en ese horario.", "warning")
                return redirect(url_for("doctor_appointments_new"))

            # Crea la cita
            c = Cita(
                medico_id=medico_id,
                paciente_id=paciente_id,
                start_at=start_at,
                end_at=end_at,
                estado=EstadoCita.PENDIENTE,
                notas=notas,
            )
            db.add(c)

        flash("Cita creada correctamente.", "success")
        return redirect(url_for("doctor_consultas"))

    # GET: renderiza formulario
    return render_template(
        "doctor_appointments_new.html",
        medicos=medicos,
        pacientes=pacientes,
        medico_actual=medico_actual,
    )



# ----------------- DOCTORES -----------------
@app.route("/doctores")
@login_required
def doctores_list():
    if current_user.tipo not in (TipoUsuario.ADMIN, TipoUsuario.MEDICO):
        abort(403)
    with get_db() as db:
        doctores = db.query(Medico).options(joinedload(Medico.usuario)).order_by(Medico.id.asc()).all()
    return render_template("doctores_list.html", doctores=doctores)


@app.route("/doctor/<int:medico_id>")
@login_required
def doctor_perfil(medico_id: int):
    with get_db() as db:
        medico = (
            db.query(Medico)
            .options(joinedload(Medico.usuario))
            .filter(Medico.id == medico_id)
            .first()
        )
        if not medico:
            flash("Médico no encontrado", "warning")
            return redirect(url_for("dashboard"))

        es_admin = current_user.tipo == TipoUsuario.ADMIN
        es_el_mismo_medico = False
        if current_user.tipo == TipoUsuario.MEDICO:
            medico_actual = db.query(Medico).filter(Medico.usuario_id == current_user.id).first()
            es_el_mismo_medico = bool(medico_actual and medico_actual.id == medico.id)

        if not (es_admin or es_el_mismo_medico):
            abort(403)

        hoy_inicio = datetime.combine(datetime.today().date(), time.min)
        citas = (
            db.query(Cita)
            .options(
                joinedload(Cita.paciente),
                joinedload(Cita.medico).joinedload(Medico.usuario),
            )
            .filter(
                Cita.medico_id == medico.id,
                Cita.start_at >= hoy_inicio,
            )
            .order_by(Cita.start_at.asc())
            .all()
        )

        pacientes = (
            db.query(Usuario)
            .join(Cita, Cita.paciente_id == Usuario.id)
            .filter(Cita.medico_id == medico.id)
            .distinct()
            .order_by(Usuario.apellido.asc(), Usuario.nombre.asc())
            .all()
        )

    puede_editar_expediente = es_admin or es_el_mismo_medico
    return render_template(
        "doctor_perfil.html",
        medico=medico,
        citas=citas,
        pacientes=pacientes,
        EstadoCita=EstadoCita,
        puede_editar_expediente=puede_editar_expediente
    )


@app.route("/doctor/consultas")
@login_required
def doctor_consultas():
    if current_user.tipo != TipoUsuario.MEDICO:
        abort(403)

    paciente_id = request.args.get("paciente_id", type=int)

    with get_db() as db:
        medico = db.query(Medico).filter(Medico.usuario_id == current_user.id).first()
        if not medico:
            flash("No hay registro de médico asociado a tu usuario.", "warning")
            return redirect(url_for("dashboard"))

        ahora = datetime.now()
        q = (
            db.query(Cita)
            .options(
                joinedload(Cita.paciente),
                joinedload(Cita.medico).joinedload(Medico.usuario),
            )
            .filter(
                Cita.medico_id == medico.id,
                Cita.start_at >= ahora,
                Cita.estado.in_([EstadoCita.PENDIENTE, EstadoCita.CONFIRMADA]),
            )
        )
        selected_paciente = None
        if paciente_id:
            q = q.filter(Cita.paciente_id == paciente_id)
            selected_paciente = db.get(Usuario, paciente_id)

        citas = q.order_by(Cita.start_at.asc()).all()

    return render_template(
        "doctor_consultas.html",
        citas=citas,
        EstadoCita=EstadoCita,
        selected_paciente=selected_paciente
    )


@app.route("/doctor/consultas/concluidas")
@login_required
def doctor_concluidas():
    if current_user.tipo != TipoUsuario.MEDICO:
        abort(403)

    with get_db() as db:
        medico = db.query(Medico).filter(Medico.usuario_id == current_user.id).first()
        if not medico:
            flash("No hay registro de médico asociado a tu usuario.", "warning")
            return redirect(url_for("dashboard"))

        citas = (
            db.query(Cita)
            .options(
                joinedload(Cita.paciente),
                joinedload(Cita.medico).joinedload(Medico.usuario),
            )
            .filter(
                Cita.medico_id == medico.id,
                Cita.estado.in_([EstadoCita.ATENDIDA, EstadoCita.CANCELADA]),
            )
            .order_by(Cita.start_at.desc())
            .all()
        )

    return render_template("doctor_concluidas.html", citas=citas, EstadoCita=EstadoCita)


@app.route("/doctor/expedientes")
@login_required
def doctor_expedientes():
    """Lista de pacientes atendidos por el doctor con acceso a sus expedientes."""
    if current_user.tipo != TipoUsuario.MEDICO:
        abort(403)

    with get_db() as db:
        medico = db.query(Medico).filter(Medico.usuario_id == current_user.id).first()
        if not medico:
            flash("No hay registro de médico asociado a tu usuario.", "warning")
            return redirect(url_for("dashboard"))

        pacientes = (
            db.query(Usuario)
            .join(Cita, Cita.paciente_id == Usuario.id)
            .filter(Cita.medico_id == medico.id)
            .distinct()
            .order_by(Usuario.apellido.asc(), Usuario.nombre.asc())
            .all()
        )

        # El propio médico puede editar expedientes
    return render_template(
        "doctor_expedientes.html",
        pacientes=pacientes,
        puede_editar_expediente=True,
    )


@app.route("/doctor/pacientes/nuevo", methods=["GET", "POST"])
@login_required
def doctor_paciente_new():
    """
    El médico registra a un nuevo paciente y agenda su primera cita en un solo paso.
    Opción B: muestra la contraseña temporal mediante flash y redirige.
    """
    if current_user.tipo not in (TipoUsuario.MEDICO, TipoUsuario.ADMIN):
        abort(403)

    from sqlalchemy.orm import joinedload
    import secrets

    # Cargar médicos para el select (preselecciona al médico actual si existe)
    with get_db() as db:
        medicos = db.query(Medico).options(joinedload(Medico.usuario)).all()
        medico_actual = None
        if current_user.tipo == TipoUsuario.MEDICO:
            medico_actual = db.query(Medico).filter(Medico.usuario_id == current_user.id).first()

    if request.method == "POST":
        # ---- Datos del paciente ----
        nombre = (request.form.get("nombre") or "").strip()
        apellido = (request.form.get("apellido") or "").strip()
        email = (request.form.get("email") or "").strip().lower()  # opcional

        # ---- Datos de la cita ----
        try:
            medico_id = int(request.form["medico_id"])
            start_at = datetime.fromisoformat(request.form["start_at"])
            end_at = datetime.fromisoformat(request.form["end_at"])
        except Exception:
            flash("Completa médico e intervalos con un formato válido.", "warning")
            return redirect(url_for("doctor_paciente_new"))

        notas = request.form.get("notas") or None

        if not (nombre and apellido):
            flash("Nombre y apellido del paciente son obligatorios.", "warning")
            return redirect(url_for("doctor_paciente_new"))

        if end_at <= start_at:
            flash("La hora de fin debe ser posterior al inicio.", "warning")
            return redirect(url_for("doctor_paciente_new"))

        # Crear paciente + cita
        with get_db() as db:
            # Correo único solo si se proporcionó
            if email and db.query(Usuario).filter(Usuario.email == email).first():
                flash("El correo ya está registrado.", "warning")
                return redirect(url_for("doctor_paciente_new"))

            # Genera password temporal (no se pide en el form)
            temp_password = secrets.token_urlsafe(8)[:10]

            u = Usuario(
                nombre=nombre,
                apellido=apellido,
                email=email or f"paciente{secrets.randbelow(999999)}@local",
                password_hash=generate_password_hash(temp_password),
                tipo=TipoUsuario.PACIENTE,
            )
            db.add(u)
            db.flush()  # u.id disponible

            # Crear expediente vacío si no existe
            if not db.query(Expediente).filter(Expediente.paciente_id == u.id).first():
                db.add(Expediente(paciente_id=u.id))

            # Validación de traslape
            if has_overlap(db, medico_id, start_at, end_at):
                db.rollback()
                flash("El médico ya tiene una cita en ese horario.", "warning")
                return redirect(url_for("doctor_paciente_new"))

            cita = Cita(
                medico_id=medico_id,
                paciente_id=u.id,
                start_at=start_at,
                end_at=end_at,
                estado=EstadoCita.PENDIENTE,
                notas=notas,
            )
            db.add(cita)

        # Opción B: mostramos la contraseña temporal con flash y redirigimos
        flash(
            f"Paciente creado: {nombre} {apellido}. "
            f"Contraseña temporal: {temp_password}. "
            f"Se agendó la cita del {start_at.strftime('%d/%m/%Y %H:%M')} al {end_at.strftime('%d/%m/%Y %H:%M')}.",
            "info",
        )
        return redirect(url_for("doctor_consultas"))

    # GET: renderiza el formulario
    return render_template(
        "patient_new.html",
        medicos=medicos,
        medico_actual=medico_actual,
    )

# ----------------- EXPEDIENTE -----------------
@app.route("/expediente/<int:paciente_id>")
@login_required
def expediente_view(paciente_id: int):
    # Paciente solo ve el suyo; médico/admin pueden ver cualquiera
    if current_user.tipo == TipoUsuario.PACIENTE and current_user.id != paciente_id:
        abort(403)

    with get_db() as db:
        paciente = db.get(Usuario, paciente_id)
        if not paciente:
            flash("Paciente no encontrado", "warning")
            return redirect(url_for("dashboard"))

        expediente = (
            db.query(Expediente)
            .options(joinedload(Expediente.paciente))
            .filter(Expediente.paciente_id == paciente_id)
            .first()
        )

    puede_editar = current_user.tipo in (TipoUsuario.MEDICO, TipoUsuario.ADMIN)
    return render_template(
        "expediente_view.html",
        paciente=paciente,
        expediente=expediente,
        puede_editar=puede_editar
    )


@app.route("/expediente/<int:paciente_id>/editar", methods=["GET", "POST"])
@login_required
def expediente_edit(paciente_id: int):
    if current_user.tipo not in (TipoUsuario.MEDICO, TipoUsuario.ADMIN):
        abort(403)

    with get_db() as db:
        paciente = db.get(Usuario, paciente_id)
        if not paciente:
            flash("Paciente no encontrado", "warning")
            return redirect(url_for("dashboard"))

        expediente = db.query(Expediente).filter(Expediente.paciente_id == paciente_id).first()

        if request.method == "POST":
            antecedentes = request.form.get("antecedentes") or None
            alergias = request.form.get("alergias") or None
            notas = request.form.get("notas_clinicas") or None

            if not expediente:
                expediente = Expediente(
                    paciente_id=paciente_id,
                    antecedentes=antecedentes,
                    alergias=alergias,
                    notas_clinicas=notas,
                )
                db.add(expediente)
            else:
                expediente.antecedentes = antecedentes
                expediente.alergias = alergias
                expediente.notas_clinicas = notas

            flash("Expediente guardado", "success")
            return redirect(url_for("expediente_view", paciente_id=paciente_id))

    # GET (segunda consulta para hidratar si hizo rollback previo)
    with get_db() as db:
        expediente = db.query(Expediente).filter(Expediente.paciente_id == paciente_id).first()

    return render_template("expediente_edit.html", paciente=paciente, expediente=expediente)


# ----------------- RUN -----------------
# al final de app.py
if __name__ == "__main__":
    import os, webbrowser, threading, time

    def open_browser():
        # pequeña espera para que el server arranque
        time.sleep(0.8)
        webbrowser.open(f"http://127.0.0.1:{os.environ.get('PORT', 5000)}")

    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
