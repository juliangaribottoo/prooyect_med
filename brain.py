"""
Conexión con Gemini. Memoria de usuario: instrucciones de sistema
basadas en errores previos del asesor en la DB.
"""
import os
import json
import re
import time
from typing import Optional, List, Dict, Any
import google.generativeai as genai
from database import (
    obtener_errores_previos_usuario,
    obtener_caso_aleatorio,
    obtener_caso_por_categoria_aleatorio,
)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODELO = "gemini-2.5-flash"
MAX_REINTENTOS_CUOTA = 2
SEGUNDOS_ESPERA_CUOTA = 18


def _es_error_cuota(exc: Exception) -> bool:
    """Detecta si el error es por cuota/rate limit (429)."""
    msg = str(exc).lower()
    return "429" in str(exc) or "quota" in msg or "rate" in msg or "retry" in msg


def _extraer_segundos_retry(exc: Exception) -> int:
    """Extrae 'Please retry in X.XXs' del mensaje de error."""
    match = re.search(r"retry in (\d+(?:\.\d+)?)\s*s", str(exc), re.I)
    if match:
        return max(1, int(float(match.group(1))) + 1)
    return SEGUNDOS_ESPERA_CUOTA


def _get_api_key():
    """Obtiene la API key de Gemini desde env o Streamlit secrets."""
    try:
        import streamlit as st
        return GEMINI_API_KEY or st.secrets.get("GEMINI_API_KEY", "")
    except Exception:
        return GEMINI_API_KEY


def _construir_instrucciones_sistema(
    email_asesor: str,
    caso: Optional[Dict[str, Any]],
    categoria_humana: Optional[str] = None,
    perfil_label: Optional[str] = None,
    perfil_descripcion: Optional[str] = None,
) -> str:
    """
    Construye el system instruction para Gemini:
    - Personificar el caso real elegido.
    - Adaptar el rol del cliente (tipo de asociado).
    - Ser un cliente difícil si el asesor no cumple el manual.
    - Incluir puntos débiles del asesor (errores previos) para ponerlo a prueba.
    """
    partes = [
        "Eres un simulador de cliente de una prepaga de salud. Debes personificar al cliente "
        "según el caso que te indiquen. Eres un cliente exigente: si el asesor no sigue el "
        "manual de atención (cordialidad, verificación de datos, explicación clara de coberturas "
        "y trámites), debes mostrarte molesto o pedir hablar con un supervisor. Responde siempre "
        "en primera persona, como el cliente. Sé breve en cada mensaje (1-3 oraciones). "
        "No reveles que eres una IA ni que es una simulación."
    ]

    if categoria_humana:
        partes.append(
            f"\n\nTIPO DE SIMULACIÓN SELECCIONADO POR EL ASESOR: {categoria_humana}."
        )

    if perfil_label:
        descripcion = perfil_descripcion or ""
        partes.append(
            f"\n\nTIPO DE ASOCIADO (ROL DEL CLIENTE): {perfil_label}.\n"
            f"Comportamiento esperado en la conversación: {descripcion}"
        )

    if caso:
        partes.append(
            f"\n\nCASO A PERSONIFICAR:\n"
            f"Categoría: {caso.get('categoria', 'N/A')}\n"
            f"Título: {caso.get('titulo', 'N/A')}\n"
            f"Contexto (anonimizado): {caso.get('contexto_anonimo', '')}"
        )

    errores_previos = obtener_errores_previos_usuario(email_asesor, limite=10)
    if errores_previos:
        puntos_debilidad = []
        for ev in errores_previos:
            if ev.get("errores"):
                puntos_debilidad.append(ev["errores"])
            if ev.get("feedback_json"):
                try:
                    fb = json.loads(ev["feedback_json"])
                    if isinstance(fb, list):
                        puntos_debilidad.extend([str(x) for x in fb])
                    elif isinstance(fb, dict) and "puntos_mejora" in fb:
                        puntos_debilidad.extend(fb["puntos_mejora"])
                except (json.JSONDecodeError, TypeError):
                    pass
        if puntos_debilidad:
            partes.append(
                "\n\nPUNTOS EN LOS QUE ESTE ASESOR HA FALLADO ANTES (ponlo a prueba en estos aspectos):\n"
                + "\n".join(f"- {p}" for p in puntos_debilidad[:15])
            )

    return "\n".join(partes).strip()


def iniciar_chat(
    email_asesor: str,
    categoria: Optional[str] = None,
    categoria_humana: Optional[str] = None,
    perfil_label: Optional[str] = None,
    perfil_descripcion: Optional[str] = None,
) -> Optional[Any]:
    """
    Inicializa el modelo Gemini con instrucciones de sistema que incluyen:
    - memoria de usuario (errores previos),
    - caso real aleatorio (posiblemente filtrado por categoría),
    - tipo de asociado (rol del cliente).
    Retorna el objeto chat o None si no hay API key.
    """
    api_key = _get_api_key()
    if not api_key:
        return None

    genai.configure(api_key=api_key)
    if categoria:
        caso = obtener_caso_por_categoria_aleatorio(categoria) or obtener_caso_aleatorio()
    else:
        caso = obtener_caso_aleatorio()
    system_instruction = _construir_instrucciones_sistema(
        email_asesor,
        caso,
        categoria_humana=categoria_humana,
        perfil_label=perfil_label,
        perfil_descripcion=perfil_descripcion,
    )

    model = genai.GenerativeModel(
        MODELO,
        system_instruction=system_instruction,
    )
    return model.start_chat(history=[])


def enviar_mensaje(chat: Any, mensaje_usuario: str) -> str:
    """Envía un mensaje al chat de Gemini y devuelve la respuesta en texto. Reintenta si hay 429 (cuota)."""
    ultimo_error = None
    for intento in range(MAX_REINTENTOS_CUOTA + 1):
        try:
            response = chat.send_message(mensaje_usuario)
            return response.text or ""
        except Exception as e:
            ultimo_error = e
            if _es_error_cuota(e) and intento < MAX_REINTENTOS_CUOTA:
                segundos = _extraer_segundos_retry(e)
                time.sleep(segundos)
                continue
            break
    if _es_error_cuota(ultimo_error):
        return (
            "[Cuota de la API agotada. Espera unos minutos o revisa tu plan en "
            "https://ai.google.dev/gemini-api/docs/rate-limits. Puedes volver a intentar.]"
        )
    return f"[Error al conectar con la IA: {str(ultimo_error)}]"


def generar_reporte_final(transcripcion: str, email_asesor: str) -> Dict[str, Any]:
    """
    Cuando el asesor escribe /finalizar, se envía la transcripción a Gemini
    para que genere puntaje, errores y feedback en formato estructurado.
    """
    api_key = _get_api_key()
    if not api_key:
        return {
            "puntaje": 0,
            "errores": "API key de Gemini no configurada.",
            "feedback_json": "[]",
            "resumen": "No se pudo generar el reporte.",
        }

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(MODELO)

    prompt = f"""Eres un evaluador de calidad de atención al cliente de una prepaga.
Analiza la siguiente transcripción de una conversación entre un asesor y un cliente (simulado).
Responde ÚNICAMENTE con un JSON válido, sin markdown ni texto extra, con esta estructura exacta:
{{
  "puntaje": <número del 0 al 100>,
  "errores": "<texto breve enumerando los errores cometidos por el asesor>",
  "puntos_mejora": ["punto 1", "punto 2", "punto 3"],
  "resumen": "<párrafo breve de feedback general para el asesor>"
}}

Transcripción:
---
{transcripcion}
---
JSON:"""

    ultimo_error = None
    for intento in range(MAX_REINTENTOS_CUOTA + 1):
        try:
            response = model.generate_content(prompt)
            text = (response.text or "").strip()
            # Limpiar posible markdown
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text)
            puntaje = float(data.get("puntaje", 0))
            errores = data.get("errores", "")
            puntos_mejora = data.get("puntos_mejora", [])
            resumen = data.get("resumen", "")
            return {
                "puntaje": puntaje,
                "errores": errores,
                "feedback_json": json.dumps({"puntos_mejora": puntos_mejora, "resumen": resumen}),
                "resumen": resumen,
            }
        except json.JSONDecodeError as e:
            return {
                "puntaje": 0,
                "errores": str(e),
                "feedback_json": "[]",
                "resumen": "No se pudo analizar la conversación.",
            }
        except Exception as e:
            ultimo_error = e
            if _es_error_cuota(e) and intento < MAX_REINTENTOS_CUOTA:
                time.sleep(_extraer_segundos_retry(e))
                continue
            break
    return {
        "puntaje": 0,
        "errores": str(ultimo_error) if ultimo_error else "Error desconocido",
        "feedback_json": "[]",
        "resumen": (
            "Cuota de la API agotada. Espera unos minutos o revisa tu plan en "
            "https://ai.google.dev/gemini-api/docs/rate-limits"
            if ultimo_error and _es_error_cuota(ultimo_error)
            else "No se pudo analizar la conversación."
        ),
    }
