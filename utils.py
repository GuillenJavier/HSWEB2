from sqlalchemy.orm import Session
from models import Cita

def has_overlap(db: Session, medico_id: int, start_at, end_at, exclude_id: int | None = None) -> bool:
    """
    True si existe una cita traslapada para el mismo médico en [start_at, end_at).
    """
    q = db.query(Cita).filter(
        Cita.medico_id == medico_id,
        Cita.start_at < end_at,
        Cita.end_at > start_at,
    )
    if exclude_id is not None:
        q = q.filter(Cita.id != exclude_id)
    return db.query(q.exists()).scalar()
