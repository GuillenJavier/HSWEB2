from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session, declarative_base

DATABASE_URL = "sqlite:///health_system.db"

engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},  # requerido por SQLite en hilos
)

SessionLocal = scoped_session(
    sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,  # evita DetachedInstanceError en current_user
    )
)

Base = declarative_base()

def init_db():
    """Crea tablas si no existen."""
    from models import Usuario, Medico, Cita  # noqa: F401
    Base.metadata.create_all(bind=engine)
