"""
Aplicación Streamlit: entrenamiento de asesores de prepaga.
Frontend corporativo (azul/blanco), chat con IA, reporte al escribir /finalizar.
"""
import streamlit as st
import json
import plotly.express as px
import plotly.graph_objects as go
from database import init_db, agregar_caso_ejemplo, guardar_evaluacion
from auth import (
    login_manual,
    login_google_sso,
    get_google_oauth_url,
    logout,
    GOOGLE_CLIENT_ID,
    REDIRECT_URI,
)
from brain import iniciar_chat, enviar_mensaje, generar_reporte_final
from sync import sincronizar_evaluaciones

# ========== CONFIGURACIÓN DE ESTILO (modificar colores y fuentes aquí) ==========
CORPORATE_CSS = """
/* Variables de tema corporativo - EDITABLES */
:root {
    --color-primary: #1e3a5f;
    --color-primary-light: #2c5282;
    --color-primary-dark: #0f2744;
    --color-accent: #3182ce;
    --color-bg: #f7fafc;
    --color-surface: #ffffff;
    --color-text: #2d3748;
    --color-text-muted: #718096;
    --font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    --radius: 8px;
    --shadow: 0 1px 3px rgba(0,0,0,0.08);
}

/* Base */
.stApp {
    background: var(--color-bg) !important;
    font-family: var(--font-family) !important;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--color-primary) 0%, var(--color-primary-dark) 100%) !important;
}
[data-testid="stSidebar"] .stMarkdown, [data-testid="stSidebar"] label {
    color: #e2e8f0 !important;
}

/* Botones primarios */
.stButton > button {
    background: var(--color-primary) !important;
    color: white !important;
    border-radius: var(--radius) !important;
    font-weight: 500 !important;
    border: none !important;
    padding: 0.5rem 1rem !important;
}
.stButton > button:hover {
    background: var(--color-primary-light) !important;
    border: none !important;
}

/* Chat: mensajes del usuario */
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon"]:first-child) {
    background: var(--color-primary-light) !important;
    color: white !important;
    border-radius: var(--radius) !important;
    margin: 0.5rem 0 !important;
    padding: 0.75rem 1rem !important;
    max-width: 85% !important;
    margin-left: auto !important;
    margin-right: 0 !important;
}

/* Chat: mensajes de la IA (cliente simulado) */
[data-testid="stChatMessage"]:not(:has([data-testid="chatAvatarIcon"]:first-child)) {
    background: var(--color-surface) !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: var(--radius) !important;
    box-shadow: var(--shadow) !important;
    margin: 0.5rem 0 !important;
    max-width: 85% !important;
    margin-left: 0 !important;
    margin-right: auto !important;
}

/* Input de chat */
[data-testid="stChatInput"] textarea {
    border-radius: var(--radius) !important;
    border: 1px solid #cbd5e0 !important;
    font-family: var(--font-family) !important;
}

/* Cards / expanders */
.streamlit-expanderHeader {
    background: var(--color-surface) !important;
    border-radius: var(--radius) !important;
}
div[data-testid="stVerticalBlock"] > div {
    border-radius: var(--radius) !important;
}

/* Mobile: mejor uso del espacio */
@media (max-width: 640px) {
    .stButton > button { width: 100%; }
    [data-testid="stSidebar"] { min-width: 260px; }
}
"""


def inyectar_css():
    st.markdown(f"<style>{CORPORATE_CSS}</style>", unsafe_allow_html=True)


SIMULACION_CATEGORIAS = {
    "Autorizaciones": {
        "id": "autorizaciones",
        "descripcion": "Gestión de pedidos de autorización de prácticas, estudios y cirugías. Verificación de plan, plazos y requisitos.",
    },
    "Cartilla médica": {
        "id": "cartilla_medica",
        "descripcion": "Búsqueda y orientación sobre médicos, centros y especialidades disponibles en la cartilla.",
    },
    "Discapacidad": {
        "id": "discapacidad",
        "descripcion": "Consultas sobre cobertura, prestaciones especiales y trámites asociados a certificado de discapacidad.",
    },
    "ABM de cliente (Alta/Baja/Modificación)": {
        "id": "abm_cliente",
        "descripcion": "Altas de nuevos afiliados, bajas y modificaciones de datos o plan del cliente.",
    },
}


ASOCIADO_PERFILES = {
    "Asociado emocional": {
        "id": "emocional",
        "descripcion": "Asociado que agrega una fuerte carga emocional al contacto. Se muestra angustiado, molesto o muy preocupado. Necesita contención además de la resolución técnica.",
    },
    "Asociado resolutivo": {
        "id": "resolutivo",
        "descripcion": "Asociado directo, orientado a resultados. Solo quiere saber qué hacer, dónde, cuándo y cómo. No le interesan explicaciones extensas ni empatía extra.",
    },
    "Asociado empático": {
        "id": "empatico",
        "descripcion": "Asociado cordial y de buena predisposición. No tiene un reclamo fuerte, busca conciliar y entender las opciones disponibles.",
    },
    "Botón rojo (urgencia médica)": {
        "id": "boton_rojo",
        "descripcion": "Asociado en un contexto de urgencia médica grave. Necesita resolver un tema con suma urgencia (autorización, derivación, cobertura en guardia, etc.). Tiene poco tiempo y alta ansiedad.",
    },
}


def seleccionar_categoria_simulacion():
    """Permite elegir el tipo de chat/simulación antes de iniciar el caso."""
    st.markdown("### ¿Qué tipo de caso querés practicar hoy?")
    opciones = list(SIMULACION_CATEGORIAS.keys())
    seleccion = st.radio(
        "Selecciona una categoría de simulación:",
        opciones,
        index=0 if "categoria_label" not in st.session_state else opciones.index(st.session_state["categoria_label"]),
    )
    datos = SIMULACION_CATEGORIAS[seleccion]

    # Si cambia la categoría, se reinicia confirmación y contexto de chat/perfil
    if st.session_state.get("categoria_id") != datos["id"]:
        st.session_state["categoria_confirmada"] = False
        st.session_state["perfil_confirmado"] = False
        for key in ["perfil_id", "perfil_label", "perfil_descripcion", "chat", "chat_categoria", "historial_chat", "transcripcion", "mostrar_reporte", "reporte_actual"]:
            if key in st.session_state:
                del st.session_state[key]

    st.session_state["categoria_id"] = datos["id"]
    st.session_state["categoria_label"] = seleccion

    st.markdown("#### Descripción del escenario")
    st.info(datos["descripcion"])
    st.markdown(
        "_Ejemplos típicos de conversación: confirmar datos del afiliado, explicar pasos, aclarar coberturas y tiempos de respuesta._"
    )

    if st.button("Continuar con este tipo de caso", use_container_width=True):
        st.session_state["categoria_confirmada"] = True
        st.rerun()


def seleccionar_tipo_asociado():
    """Pantalla para elegir el perfil del asociado (rol de la IA) antes del chat."""
    st.markdown("### ¿Qué tipo de asociado te está contactando?")
    opciones = list(ASOCIADO_PERFILES.keys())
    indice = 0
    if "perfil_label" in st.session_state and st.session_state["perfil_label"] in opciones:
        indice = opciones.index(st.session_state["perfil_label"])

    seleccion = st.radio(
        "Selecciona el perfil del asociado (rol de la IA):",
        opciones,
        index=indice,
    )
    datos = ASOCIADO_PERFILES[seleccion]

    st.session_state["perfil_id"] = datos["id"]
    st.session_state["perfil_label"] = seleccion
    st.session_state["perfil_descripcion"] = datos["descripcion"]

    st.markdown("#### Perfil del asociado")
    st.info(datos["descripcion"])
    st.markdown(
        "_Piensa cómo adaptarías tu tono, tus tiempos y la forma de explicar dependiendo de este perfil._"
    )

    if st.button("Aceptar este perfil y ver el chat", use_container_width=True):
        st.session_state["perfil_confirmado"] = True
        st.rerun()


def pagina_login():
    """Pantalla de login: Google SSO + formulario manual."""
    st.markdown("## Entrenamiento de Asesores")
    st.markdown("Inicie sesión para continuar.")

    # Callback de Google OAuth
    query_params = st.query_params
    if "code" in query_params:
        code = query_params["code"]
        ok, msg, email = login_google_sso(code)
        if ok and email:
            st.session_state["logged_in"] = True
            st.session_state["email"] = email
            st.query_params.clear()
            st.rerun()
        else:
            st.error(msg)
        return

    # Botón Google SSO (solo si está configurado)
    if GOOGLE_CLIENT_ID and REDIRECT_URI:
        oauth_url = get_google_oauth_url()
        st.link_button("Iniciar sesión con Google", oauth_url, type="primary")
        st.markdown("---")

    # Login manual
    with st.form("login_manual"):
        email = st.text_input("Email", placeholder="tu@email.com")
        password = st.text_input("Contraseña", type="password")
        submitted = st.form_submit_button("Entrar")
        if submitted and email and password:
            ok, msg = login_manual(email.strip(), password)
            if ok:
                st.session_state["logged_in"] = True
                st.session_state["email"] = email.strip()
                st.rerun()
            else:
                st.error(msg)


def sidebar():
    """Sidebar con perfil y logout."""
    with st.sidebar:
        st.markdown("### Perfil")
        st.caption(st.session_state.get("email", ""))
        if st.session_state.get("categoria_label"):
            st.markdown("### Simulación")
            st.caption(st.session_state["categoria_label"])
        if st.session_state.get("perfil_label"):
            st.markdown("### Tipo de asociado")
            st.caption(st.session_state["perfil_label"])
        if st.button("Cerrar sesión", use_container_width=True):
            logout()
            st.rerun()
        st.markdown("---")
        # Sincronizar con Google Sheet (opcional, para admin)
        if st.button("Sincronizar con Google Sheet", use_container_width=True):
            n, msg = sincronizar_evaluaciones()
            st.caption(msg)


def render_reporte_visual(puntaje: float, errores: str, feedback_json: str, resumen: str):
    """Genera el reporte visual con Score y puntos de mejora (Plotly + métricas)."""
    st.subheader("Reporte de evaluación")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Puntaje", f"{int(puntaje)}/100")
    with col2:
        color = "normal" if puntaje >= 70 else "off"
        st.metric("Estado", "Aprobado" if puntaje >= 70 else "A mejorar", delta=None)
    with col3:
        st.metric("Feedback", "Completado", delta=None)

    # Gauge con Plotly
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=puntaje,
        number={"suffix": "/100"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": "#3182ce"},
            "steps": [
                {"range": [0, 50], "color": "#fc8181"},
                {"range": [50, 70], "color": "#fbd38d"},
                {"range": [70, 100], "color": "#9ae6b4"},
            ],
            "threshold": {
                "line": {"color": "#1e3a5f", "width": 4},
                "thickness": 0.75,
                "value": 70,
            },
        },
        title={"text": "Score de la simulación"},
    ))
    fig.update_layout(
        height=220,
        margin=dict(l=20, r=20, t=50, b=20),
        font=dict(size=14),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)

    if errores:
        st.markdown("#### Errores detectados")
        st.warning(errores)

    if resumen:
        st.markdown("#### Resumen")
        st.info(resumen)

    try:
        data = json.loads(feedback_json or "{}")
        puntos = data.get("puntos_mejora", [])
        if puntos:
            st.markdown("#### Puntos de mejora")
            for i, p in enumerate(puntos, 1):
                st.markdown(f"- **{i}.** {p}")
    except (json.JSONDecodeError, TypeError):
        pass


def chat_y_simulacion():
    """Área principal: chat con la IA (cliente simulado) y comando /finalizar."""
    email = st.session_state.get("email", "")
    categoria_id = st.session_state.get("categoria_id")
    categoria_label = st.session_state.get("categoria_label")
    perfil_id = st.session_state.get("perfil_id")
    perfil_label = st.session_state.get("perfil_label")
    perfil_descripcion = st.session_state.get("perfil_descripcion")

    if not categoria_id:
        st.warning("Selecciona primero un tipo de simulación.")
        return
    if not perfil_id:
        st.warning("Selecciona primero el tipo de asociado.")
        return

    if "chat" not in st.session_state or st.session_state.get("chat_categoria") != categoria_id or st.session_state.get("chat_perfil") != perfil_id:
        st.session_state["chat"] = iniciar_chat(
            email,
            categoria=categoria_id,
            categoria_humana=categoria_label,
            perfil_label=perfil_label,
            perfil_descripcion=perfil_descripcion,
        )
        st.session_state["chat_categoria"] = categoria_id
        st.session_state["chat_perfil"] = perfil_id
        st.session_state["historial_chat"] = []
        st.session_state["transcripcion"] = []

    chat = st.session_state["chat"]
    if chat is None:
        st.error("No se pudo conectar con la IA. Configure GEMINI_API_KEY en variables de entorno o en Secrets.")
        return

    st.markdown("### Simulación de atención al cliente")
    st.caption("Responde como si estuvieras atendiendo a un cliente real. Escribe **/finalizar** para terminar y ver tu reporte.")

    # Contenedor del chat
    container = st.container()
    with container:
        for entry in st.session_state["historial_chat"]:
            role = entry["role"]
            content = entry["content"]
            with st.chat_message(role):
                st.markdown(content)

    # Input del usuario
    if prompt := st.chat_input("Escribe tu respuesta al cliente..."):
        # Comando /finalizar
        if prompt.strip().lower() == "/finalizar":
            transcripcion_texto = "\n".join(
                f"{t['role']}: {t['content']}" for t in st.session_state["transcripcion"]
            )
            if not transcripcion_texto.strip():
                st.warning("No hay conversación para evaluar. Interactúa primero con el cliente.")
                return

            with st.spinner("Generando reporte..."):
                reporte = generar_reporte_final(transcripcion_texto, email)
            puntaje = reporte["puntaje"]
            errores = reporte["errores"]
            feedback_json = reporte["feedback_json"]
            resumen = reporte.get("resumen", "")

            guardar_evaluacion(
                email_asesor=email,
                puntaje=puntaje,
                errores=errores,
                feedback_json=feedback_json,
                transcripcion=transcripcion_texto,
            )

            st.session_state["reporte_actual"] = {
                "puntaje": puntaje,
                "errores": errores,
                "feedback_json": feedback_json,
                "resumen": resumen,
            }
            st.session_state["mostrar_reporte"] = True
            # Limpiar chat para nueva simulación
            st.session_state["chat"] = iniciar_chat(
                email,
                categoria=categoria_id,
                categoria_humana=categoria_label,
                perfil_label=perfil_label,
                perfil_descripcion=perfil_descripcion,
            )
            st.session_state["chat_categoria"] = categoria_id
            st.session_state["chat_perfil"] = perfil_id
            st.session_state["historial_chat"] = []
            st.session_state["transcripcion"] = []
            st.rerun()

        # Mensaje normal: mostrar y enviar a Gemini
        st.session_state["historial_chat"].append({"role": "user", "content": prompt})
        st.session_state["transcripcion"].append({"role": "Asesor", "content": prompt})

        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            respuesta = enviar_mensaje(chat, prompt)
            st.markdown(respuesta)

        st.session_state["historial_chat"].append({"role": "assistant", "content": respuesta})
        st.session_state["transcripcion"].append({"role": "Cliente", "content": respuesta})
        st.rerun()


def main():
    st.set_page_config(
        page_title="Entrenamiento Asesores Prepaga",
        page_icon="🏥",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    inyectar_css()

    init_db()
    agregar_caso_ejemplo()

    if not st.session_state.get("logged_in"):
        pagina_login()
        return

    sidebar()

    # Paso 1: selección de tipo de simulación (autorizaciones, cartilla, discapacidad, ABM)
    if not st.session_state.get("categoria_confirmada"):
        seleccionar_categoria_simulacion()
        return

    # Paso 2: selección del tipo de asociado (rol de la IA)
    if not st.session_state.get("perfil_confirmado"):
        seleccionar_tipo_asociado()
        return

    # Si acabamos de finalizar, mostrar reporte
    if st.session_state.get("mostrar_reporte") and st.session_state.get("reporte_actual"):
        r = st.session_state["reporte_actual"]
        render_reporte_visual(
            r["puntaje"],
            r["errores"],
            r["feedback_json"],
            r.get("resumen", ""),
        )
        if st.button("Nueva simulación"):
            st.session_state["mostrar_reporte"] = False
            st.session_state["reporte_actual"] = None
            st.rerun()
        return

    chat_y_simulacion()


if __name__ == "__main__":
    main()
