"""
Módulo de gestión de base de datos SQLite para la app de entrenamiento de asesores.
"""
import sqlite3
import json
import os
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

DB_PATH = os.environ.get("DB_PATH", "prepaga_entrenamiento.db")


@contextmanager
def get_connection():
    """Context manager para conexiones a SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Crea las tablas si no existen."""
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT,
                rol TEXT NOT NULL DEFAULT 'asesor',
                activo INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS casos_reales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                categoria TEXT NOT NULL,
                titulo TEXT NOT NULL,
                contexto_anonimo TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS evaluaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email_asesor TEXT NOT NULL,
                fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                puntaje REAL NOT NULL,
                errores TEXT,
                feedback_json TEXT,
                transcripcion TEXT,
                sincronizado INTEGER DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_evaluaciones_email 
            ON evaluaciones(email_asesor)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_evaluaciones_fecha 
            ON evaluaciones(fecha)
        """)


def get_usuario_por_email(email: str) -> Optional[Dict[str, Any]]:
    """Obtiene un usuario por email."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, email, password_hash, rol, activo FROM usuarios WHERE email = ? AND activo = 1",
            (email.lower().strip(),),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def crear_usuario(email: str, password_hash: Optional[str], rol: str = "asesor") -> bool:
    """Crea un usuario (password_hash puede ser None para SSO)."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO usuarios (email, password_hash, rol) VALUES (?, ?, ?)",
                (email.lower().strip(), password_hash, rol),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def listar_casos_reales() -> List[Dict[str, Any]]:
    """Devuelve todos los casos reales para simulación."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, categoria, titulo, contexto_anonimo FROM casos_reales ORDER BY RANDOM()"
        )
        return [dict(row) for row in cursor.fetchall()]


def obtener_caso_aleatorio() -> Optional[Dict[str, Any]]:
    """Obtiene un caso real aleatorio para la simulación."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, categoria, titulo, contexto_anonimo FROM casos_reales ORDER BY RANDOM() LIMIT 1"
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def obtener_caso_por_categoria_aleatorio(categoria: str) -> Optional[Dict[str, Any]]:
    """Obtiene un caso real aleatorio filtrado por categoría."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, categoria, titulo, contexto_anonimo
            FROM casos_reales
            WHERE categoria = ?
            ORDER BY RANDOM()
            LIMIT 1
            """,
            (categoria,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def obtener_errores_previos_usuario(email: str, limite: int = 10) -> List[Dict[str, Any]]:
    """Obtiene los errores/feedback previos del asesor para memoria de la IA."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT errores, feedback_json, puntaje 
            FROM evaluaciones 
            WHERE email_asesor = ? 
            ORDER BY fecha DESC 
            LIMIT ?
            """,
            (email.lower().strip(), limite),
        )
        return [dict(row) for row in cursor.fetchall()]


def guardar_evaluacion(
    email_asesor: str,
    puntaje: float,
    errores: Optional[str] = None,
    feedback_json: Optional[str] = None,
    transcripcion: Optional[str] = None,
) -> int:
    """Guarda una evaluación y devuelve el id insertado."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO evaluaciones (email_asesor, puntaje, errores, feedback_json, transcripcion)
            VALUES (?, ?, ?, ?, ?)
            """,
            (email_asesor.lower().strip(), puntaje, errores, feedback_json, transcripcion),
        )
        return cursor.lastrowid


def obtener_evaluaciones_pendientes_sync() -> List[Dict[str, Any]]:
    """Obtiene evaluaciones no sincronizadas con Google Sheets."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, email_asesor, fecha, puntaje, errores, feedback_json, transcripcion FROM evaluaciones WHERE sincronizado = 0"
        )
        return [dict(row) for row in cursor.fetchall()]


def marcar_evaluacion_sincronizada(evaluacion_id: int) -> None:
    """Marca una evaluación como sincronizada."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE evaluaciones SET sincronizado = 1 WHERE id = ?", (evaluacion_id,))


def agregar_caso_ejemplo() -> None:
    """Inserta un caso de ejemplo si la tabla está vacía (útil para desarrollo)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM casos_reales")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                """
                INSERT INTO casos_reales (categoria, titulo, contexto_anonimo) VALUES
                ('autorizaciones', 'Autorización de estudio ambulatorio', 'Cliente solicita autorización para un estudio de diagnóstico programado. Tiene dudas sobre copagos y plazos.'),
                ('cartilla_medica', 'Búsqueda de prestador en cartilla', 'Cliente no encuentra un especialista cerca de su domicilio y pide ayuda para encontrar opciones en la cartilla.'),
                ('discapacidad', 'Cobertura por discapacidad', 'Madre de un menor con certificado de discapacidad consulta qué prestaciones y profesionales están cubiertos y cómo gestionarlas.'),
                ('abm_cliente', 'Alta de nuevo afiliado', 'Cliente quiere sumar a su pareja al plan y consulta requisitos, tiempos de alta y documentación necesaria.')
                """
            )
