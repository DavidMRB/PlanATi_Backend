# PlanATi Backend

Backend de PlanATi construido con FastAPI para buscar, valorar y consultar establecimientos gastronomicos, administrar usuarios y preparar integraciones externas.

## Tecnologia

- Python 3.13+
- FastAPI
- SQLAlchemy 2.x
- Alembic
- PostgreSQL + PostGIS para produccion
- JWT para autenticacion
- Pydantic para validacion
- Boto3 para Cloudflare R2
- SQLite en memoria para pruebas funcionales rapidas

## Preparacion local

1. Crear y activar un entorno virtual.
2. Instalar las dependencias:

```bash
pip install -r requirements.txt
```

3. Copiar `.env.example` como `.env` y ajustar sus valores locales.
4. Iniciar PostgreSQL/PostGIS:

```bash
docker compose up -d
```

5. Iniciar el servidor:

```bash
uvicorn app.main:app --reload
```

La comprobacion inicial esta disponible en `http://localhost:8000/api/v1/health`.

## Estructura

- `app/main.py`: punto de entrada de FastAPI.
- `app/core/config.py`: configuracion central.
- `app/core/security.py`: JWT y hash de contrasenas.
- `app/api/dependencies.py`: dependencias y permisos globales.
- `app/api/routes/`: rutas por dominio.
- `app/models/`: entidades de base de datos.
- `app/schemas/`: DTOs para requests y responses.
- `app/services/`: logica de negocio.
- `app/db/`: conexion y sesiones.
- `migrations/`: migraciones de Alembic.
- `docker-compose.yml`: PostgreSQL con PostGIS para desarrollo local.

## Variables de entorno

### Base de datos

Configuracion local sugerida:

```env
DATABASE_URL=postgresql+asyncpg://planati:planati@localhost:5432/planati
```

PostgreSQL usa los siguientes valores en el archivo Compose:

- Host: `localhost`
- Puerto: `5432`
- Base: `planati`
- Usuario: `planati`
- Password: `planati`

### JWT y CORS

```env
SECRET_KEY=tu_clave_muy_segura
CORS_ORIGINS=http://localhost:3000,https://tu-dominio.com
```

### Cloudflare R2

```env
R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=tu_access_key
R2_SECRET_ACCESS_KEY=tu_secret_key
R2_BUCKET_NAME=planati-images
R2_PUBLIC_BASE_URL=https://pub-<hash>.r2.dev
```

### Google Maps

```env
GOOGLE_MAPS_API_KEY=tu_api_key
```

Esta variable solo es necesaria para la visualizacion del mapa en el frontend. No se debe incluir ninguna clave sensible en el repositorio.

## Funcionalidades y rutas principales

| Requisito | Estado | Implementacion |
|---|---|---|
| Registrar usuarios e iniciar sesion | Parcial | Registro y login implementados; los establecimientos usan autenticacion protegida. |
| Modificar perfil | Cubierto | `PATCH /api/v1/users/me` |
| Actualizar establecimientos | Cubierto | `PATCH /api/v1/establishments/{establishment_id}` |
| Buscar por nombre o categoria | Cubierto | `GET /api/v1/establishments` con `search` y `category` |
| Visualizar mapa georreferenciado | Parcial | El backend almacena coordenadas; la visualizacion corresponde al frontend. |
| Consultar establecimiento | Cubierto | `GET /api/v1/establishments/{establishment_id}` |
| Publicar resenas y puntuacion | Cubierto | `POST /api/v1/reviews/establishments/{establishment_id}` |
| Adjuntar fotografias | Parcial | Rutas de imagen y URL de carga preparadas; falta validar R2 real. |
| Responder resenas | Cubierto | `POST /api/v1/reviews/{review_id}/reply` |
| Gestion administrativa | Parcial | Usuarios, roles y estadisticas implementados; falta gestionar todo el contenido. |

### Geolocalizacion

`GET /api/v1/establishments/nearby` consulta establecimientos cercanos mediante coordenadas `lat` y `lng`, calcula la distancia con la formula haversine y ordena los resultados por proximidad.

### Almacenamiento de imagenes

- `POST /api/v1/reviews/{review_id}/images`: registra imagenes.
- `POST /api/v1/reviews/{review_id}/upload-url`: prepara una carga segura hacia Cloudflare R2.

### Administracion

- `GET /api/v1/admin/dashboard`
- `GET /api/v1/admin/users`
- `PATCH /api/v1/admin/users/{user_id}/role`

El acceso administrativo esta restringido mediante `require_admin`.

## Integraciones externas

### PostgreSQL / PostGIS

Es la base de datos recomendada para el entorno real y produccion. Almacena usuarios, establecimientos, resenas y relaciones, y permite agregar consultas espaciales posteriormente.

### Cloudflare R2

Permite generar URLs firmadas, subir imagenes desde el frontend y guardar sus URLs publicas en las resenas.

### Google Maps API

Debe utilizarse en el frontend para mostrar ubicaciones, centrar el mapa y representar distancias o rutas. El backend solo expone las coordenadas y consultas de proximidad.

## Validaciones recomendadas

### Autenticacion

- Registro valido y registro con email duplicado.
- Login valido y contrasena incorrecta.
- Rutas protegidas sin token o con token invalido.
- Consulta del usuario autenticado.

Resultados esperados: `201` para registro valido, `409` para email duplicado, `200` para login valido y `401` para credenciales invalidas o token faltante.

### Roles y administracion

- Un usuario normal recibe `403` al acceder al dashboard.
- Un administrador recibe `200`.
- Cambiar roles validos y rechazar valores no permitidos con `400`.
- Verificar conteos de usuarios, establecimientos y resenas.

### Establecimientos y resenas

- Crear, consultar, buscar y actualizar establecimientos.
- Verificar permisos del propietario con respuestas `403` cuando corresponda.
- Publicar resenas con puntuacion de 1 a 5.
- Rechazar entradas invalidas con `400` o `422`.
- Responder resenas y validar permisos del propietario.
- Consultar establecimientos cercanos y verificar el orden por distancia.

### Cloudflare R2

Sin credenciales configuradas, la generacion de URL debe devolver `503`. Con credenciales validas, debe devolver `200` y una URL presignada asociada al bucket.

## Checklist de entrega

- [ ] Backend importando sin errores.
- [ ] Autenticacion funcionando.
- [ ] Roles administrativos funcionando.
- [ ] CRUD de establecimientos funcionando.
- [ ] Resenas funcionando.
- [ ] Upload de imagenes configurado.
- [ ] Geolocalizacion base funcionando.
- [ ] Variables de entorno documentadas.
- [ ] Migraciones de Alembic listas.
- [ ] Pruebas automaticas ejecutadas con SQLite.

## Recomendaciones

- Mantener PostgreSQL + PostGIS para la version final.
- Usar SQLite en memoria solo para pruebas rapidas automatizadas.
- Mantener las variables de entorno en `.env`.
- Probar los flujos con `TestClient` y luego con PostgreSQL.
- Mantener la visualizacion de Google Maps en el frontend.
