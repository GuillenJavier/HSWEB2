from enum import Enum as PyEnum
from datetime import datetime

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import relationship
from flask_login import UserMixin

from database import Base


class TipoUsuario(str, PyEnum):
    ADMIN = "ADMIN"
    MEDICO = "MEDICO"
    PACIENTE = "PACIENTE"


class EstadoCita(str, PyEnum):
    PENDIENTE = "PENDIENTE"
    CONFIRMADA = "CONFIRMADA"
    CANCELADA = "CANCELADA"
    ATENDIDA = "ATENDIDA"


class Usuario(Base, UserMixin):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True)
    nombre = Column(String, nullable=False)
    apellido = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    tipo = Column(SAEnum(TipoUsuario), default=TipoUsuario.PACIENTE, nullable=False)

    medico = relationship("Medico", back_populates="usuario", uselist=False)
    expediente = relationship("Expediente", back_populates="paciente", uselist=False)

    def get_id(self) -> str:
        return str(self.id)


class Medico(Base):
    __tablename__ = "medicos"

    id = Column(Integer, primary_key=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, unique=True)
    especialidad = Column(String, nullable=False)

    usuario = relationship("Usuario", back_populates="medico")
    citas = relationship("Cita", back_populates="medico")


class Cita(Base):
    __tablename__ = "citas"

    id = Column(Integer, primary_key=True)
    medico_id = Column(Integer, ForeignKey("medicos.id"), nullable=False, index=True)
    paciente_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)

    start_at = Column(DateTime, nullable=False, index=True)
    end_at = Column(DateTime, nullable=False, index=True)
    estado = Column(SAEnum(EstadoCita), default=EstadoCita.PENDIENTE, nullable=False)
    notas = Column(String, nullable=True)

    medico = relationship("Medico", back_populates="citas")
    paciente = relationship("Usuario")


class Expediente(Base):
    __tablename__ = "expedientes"

    id = Column(Integer, primary_key=True)
    paciente_id = Column(Integer, ForeignKey("usuarios.id"), unique=True, nullable=False)
    antecedentes = Column(String, nullable=True)
    alergias = Column(String, nullable=True)
    notas_clinicas = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    paciente = relationship("Usuario", back_populates="expediente")
