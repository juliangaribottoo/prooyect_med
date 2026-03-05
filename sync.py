"""
Sincronización de nuevas filas de 'evaluaciones' con una Google Sheet (gspread).
Configuración: credenciales JSON de cuenta de servicio o OAuth en env/secrets.
"""
import os
import json
from typing import Optional, List, Dict, Any
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from database import (
    obtener_evaluaciones_pendientes_sync,
    marcar_evaluacion_sincronizada,
)

# Scope para Google Sheets
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

# ID de la hoja de cálculo (parte de la URL: .../d/SHEET_ID/...)
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
SHEET_NAME = os.environ.get("GOOGLE_SHEET_NAME", "Evaluaciones")


def _get_credentials():
    """Obtiene credenciales desde variable de entorno JSON o Streamlit secrets."""
    creds_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not creds_json:
        try:
            import streamlit as st
            creds_json = st.secrets.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
            if isinstance(creds_json, dict):
                creds_json = json.dumps(creds_json)
        except Exception:
            pass
    if not creds_json:
        return None
    try:
        info = json.loads(creds_json)
        return ServiceAccountCredentials.from_json_keyfile_dict(info, SCOPES)
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def _get_client() -> Optional[gspread.Client]:
    """Crea cliente gspread autorizado."""
    creds = _get_credentials()
    if not creds:
        return None
    return gspread.authorize(creds)


def _row_from_evaluacion(ev: Dict[str, Any]) -> List[Any]:
    """Convierte una fila de evaluación a lista para append_row."""
    return [
        ev.get("id"),
        ev.get("email_asesor", ""),
        ev.get("fecha", ""),
        ev.get("puntaje", 0),
        ev.get("errores", "") or "",
        ev.get("feedback_json", "") or "",
        (ev.get("transcripcion", "") or "")[:50000],  # límite razonable por celda
    ]


def sincronizar_evaluaciones() -> tuple:
    """
    Envía cada nueva fila de evaluaciones a la Google Sheet y las marca como sincronizadas.
    Retorna (cantidad_enviada, mensaje).
    """
    sheet_id = SHEET_ID
    if not sheet_id:
        try:
            import streamlit as st
            sheet_id = st.secrets.get("GOOGLE_SHEET_ID", "")
        except Exception:
            pass
    if not sheet_id:
        return 0, "GOOGLE_SHEET_ID no configurado."

    client = _get_client()
    if not client:
        return 0, "Credenciales de Google (cuenta de servicio) no configuradas."

    try:
        spreadsheet = client.open_by_key(sheet_id)
    except Exception as e:
        return 0, f"No se pudo abrir la hoja: {e}"

    try:
        worksheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=1000, cols=10)
        worksheet.append_row([
            "id", "email_asesor", "fecha", "puntaje", "errores", "feedback_json", "transcripcion"
        ])

    pendientes = obtener_evaluaciones_pendientes_sync()
    if not pendientes:
        return 0, "No hay evaluaciones pendientes de sincronizar."

    enviadas = 0
    for ev in pendientes:
        try:
            row = _row_from_evaluacion(ev)
            worksheet.append_row(row, value_input_option="RAW")
            marcar_evaluacion_sincronizada(ev["id"])
            enviadas += 1
        except Exception as e:
            return enviadas, f"Error al enviar evaluación {ev['id']}: {e}"

    return enviadas, f"Se sincronizaron {enviadas} evaluación(es) correctamente."
