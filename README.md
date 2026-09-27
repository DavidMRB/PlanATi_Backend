# PlanATi Backend

Backend de PlanATi construido con FastAPI.

## Preparacion local

1. Crear y activar un entorno virtual.
2. Instalar las dependencias:

```bash
pip install -r requirements.txt
```

3. Copiar `.env.example` como `.env` y ajustar sus valores locales.
4. Iniciar el servidor:

```bash
uvicorn app.main:app --reload
```

La comprobacion inicial esta disponible en `http://localhost:8000/api/v1/health`.

La logica de negocio, modelos, migraciones y autenticacion se agregaran en las siguientes fases. Esta base no incluye todavia pantallas complejas ni integraciones externas.
