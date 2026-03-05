"""
Módulo de autenticación: Google SSO (OAuth2) y login manual contra DB.
Dominio permitido para Google: configurable vía GOOGLE_ALLOWED_DOMAIN (ej: nombreempresa.com).
"""
import os
from typing import Optional, Tuple
import bcrypt
import streamlit as st
from urllib.parse import urlencode
import requests
from database import get_usuario_por_email, crear_usuario, init_db

# Dominio permitido para Google SSO (ej: nombreempresa.com)
GOOGLE_ALLOWED_DOMAIN = os.environ.get("GOOGLE_ALLOWED_DOMAIN", "nombreempresa.com").lower().replace("@", "")

def _get_secret(key: str, default: str = "") -> str:
    """Lee secret desde env o Streamlit secrets (sin fallar si no existe)."""
    v = os.environ.get(key)
    if v:
        return v
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


# OAuth2 Google - configurar en Hostinger/Streamlit secrets o env
GOOGLE_CLIENT_ID = _get_secret("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = _get_secret("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = _get_secret("OAUTH_REDIRECT_URI")


def hash_password(password: str) -> str:
    """Genera hash bcrypt de la contraseña."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verifica contraseña contra hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def email_pertenece_dominio(email: str) -> bool:
    """Comprueba si el email pertenece al dominio permitido (@nombreempresa.com)."""
    if not email or "@" not in email:
        return False
    dominio = email.split("@")[-1].lower()
    return dominio == GOOGLE_ALLOWED_DOMAIN


def get_google_oauth_url() -> str:
    """Genera la URL de autorización de Google OAuth2."""
    base = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{base}?{urlencode(params)}"


def intercambiar_codigo_por_token(code: str) -> dict:
    """Intercambia el código de autorización por tokens y devuelve id_token / userinfo."""
    resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    access_token = data.get("access_token")
    if not access_token:
        raise ValueError("No access_token in response")

    # Obtener email desde userinfo
    user_resp = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    user_resp.raise_for_status()
    return user_resp.json()


def login_manual(email: str, password: str) -> Tuple[bool, str]:
    """
    Login contra tabla usuarios. Retorna (éxito, mensaje).
    """
    init_db()
    user = get_usuario_por_email(email)
    if not user:
        return False, "Usuario no encontrado o inactivo."
    if not user.get("password_hash"):
        return False, "Este usuario debe iniciar sesión con Google."
    if not verify_password(password, user["password_hash"]):
        return False, "Contraseña incorrecta."
    return True, "OK"


def login_google_sso(code: str) -> Tuple[bool, str, Optional[str]]:
    """
    Procesa el callback de Google OAuth2.
    Retorna (éxito, mensaje, email o None).
    """
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not REDIRECT_URI:
        return False, "Google SSO no configurado. Defina GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET y OAUTH_REDIRECT_URI.", None

    try:
        userinfo = intercambiar_codigo_por_token(code)
    except Exception as e:
        return False, f"Error al verificar con Google: {str(e)}", None

    email = (userinfo.get("email") or "").lower().strip()
    if not email:
        return False, "No se pudo obtener el email de Google.", None

    if not email_pertenece_dominio(email):
        return False, f"Solo se permiten cuentas del dominio @{GOOGLE_ALLOWED_DOMAIN}.", None

    init_db()
    user = get_usuario_por_email(email)
    if not user:
        crear_usuario(email, password_hash=None, rol="asesor")
    return True, "OK", email


def logout():
    """Limpia la sesión de Streamlit."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
