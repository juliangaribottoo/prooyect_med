# Entrenamiento de Asesores - Prepaga

App modular de entrenamiento para asesores de prepaga (Streamlit + Python), lista para desplegar en Hostinger.

## Ejecución local

```bash
cd prepaga-asesores
pip install -r requirements.txt
set GEMINI_API_KEY=tu_api_key
streamlit run app.py
```

## Despliegue en Hostinger

1. Sube el proyecto (por FTP o Git) a la carpeta que use tu plan (ej. `python` o `public_html` según configuración).
2. En el panel de Hostinger, configura **Python** y apunta el comando de inicio a:
   ```bash
   pip install -r requirements.txt && streamlit run app.py --server.port 8501 --server.address 0.0.0.0
   ```
3. Variables de entorno (o Secrets en Streamlit Cloud si usas otra plataforma):
   - `GEMINI_API_KEY`: API key de Google AI Studio (Gemini).
   - `GOOGLE_ALLOWED_DOMAIN`: dominio permitido para SSO (ej. `nombreempresa.com`).
   - Para Google SSO: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `OAUTH_REDIRECT_URI` (URL de tu app).
   - Para Google Sheet: `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_JSON` (JSON de cuenta de servicio).

## Primer usuario (login manual)

La tabla `usuarios` debe tener al menos un usuario. Desde Python:

```python
from database import init_db, crear_usuario
from auth import hash_password

init_db()
crear_usuario("admin@tudominio.com", hash_password("tu_password"), "asesor")
```

## Personalizar colores y fuentes

En `app.py`, busca la variable `CORPORATE_CSS` y edita las variables CSS en `:root` (--color-primary, --font-family, etc.).
