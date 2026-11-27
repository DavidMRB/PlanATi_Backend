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

Para ejecutar las pruebas instala también las dependencias de desarrollo:

```bash
pip install -r requirements-dev.txt
pytest
```

### Google OAuth y OTP simulado

Configura `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` y `GOOGLE_REDIRECT_URI` en `.env`.
La URI de redirección debe coincidir exactamente con la configurada en Google Cloud.
El proveedor por defecto es `SMS_PROVIDER=mock`; el código OTP aparece únicamente en
los logs locales del backend y no se devuelve en la respuesta HTTP.

El flujo es:

1. Solicitar `GET /api/v1/auth/google`.
2. Abrir la `authorization_url` devuelta y completar Google.
3. Google vuelve a `/api/v1/auth/google/callback`, que redirige al frontend con un código temporal.
4. El frontend canjea el código en `POST /api/v1/auth/google/exchange`: la sesión queda en la cookie
   HttpOnly y la respuesta trae el `csrf_token` (ver "Sesión y protección CSRF").
5. Solicitar `POST /api/v1/auth/phone/send-code`.
6. Leer el OTP en los logs locales y enviarlo a `POST /api/v1/auth/phone/verify`.

Ejecuta las migraciones con:

```bash
python -m alembic upgrade head
```

Las rutas que crean o modifican establecimientos, reseñas y administración requieren
un usuario `ACTIVE` con teléfono verificado. La sesión viaja en una cookie HttpOnly
(el JWT nunca va en el JSON ni en la URL); `POST /api/v1/auth/logout` devuelve `204`
y borra la cookie.

### Sesión y protección CSRF

Toda petición `POST`, `PUT`, `PATCH` o `DELETE` pasa por dos comprobaciones
(`app/core/csrf.py`):

1. **Origen:** la cabecera `Origin` (o, si falta, el `Referer`) debe estar en
   `CSRF_TRUSTED_ORIGINS` (vacío = `CORS_ORIGINS` + `FRONTEND_URL`). Sin ninguna de
   las dos solo se rechaza si la petición trae la cookie de sesión.
2. **Token por sesión:** con la cookie de sesión, la cabecera `X-CSRF-Token` debe
   coincidir con el token de esa sesión. El token llega en `csrf_token` al iniciar
   sesión (login, registros y canje de Google) y se puede pedir de nuevo con
   `GET /api/v1/auth/csrf` (por ejemplo, al recargar la página). Login, registros,
   canje de Google y logout están exentos del token, no del origen.

Las peticiones con `Authorization: Bearer …` están exentas. Un rechazo responde
`403` con `{"detail": "...", "code": "CSRF_FAILED"}`. Para probar con `curl`, usa
Bearer o envía `Origin: http://localhost:3000` y `X-CSRF-Token`.

### Configuración de producción

Con `APP_ENV=production` la API no arranca si `SECRET_KEY` es débil o un valor por
defecto, si las URL no usan `https://` o apuntan a `localhost`, si `SMS_PROVIDER=mock`,
si `DATABASE_URL` usa `planati`/`planati` o si las variables de R2 conservan los
marcadores de `.env.example` (`app/core/startup_checks.py`). En producción la cookie
siempre es `Secure` y `/docs` queda desactivado salvo `ENABLE_API_DOCS=true`.

### Zona horaria

Las fechas se guardan y comparan en UTC (`app/core/time.py`). `APP_TIMEZONE`
(`America/Bogota`) solo se usa para validar horarios, armar textos y calcular el
inicio del día de los límites diarios. En Windows, `zoneinfo` necesita el paquete
`tzdata` (incluido en `requirements.txt`).

El registro tradicional mediante `POST /api/v1/auth/register` solicita el número
de teléfono y envía el OTP inmediatamente. Devuelve un JWT provisional para
iniciar la sesión, pero el usuario debe confirmar el código antes de usar
funciones protegidas. El OTP no se devuelve en la respuesta; con el proveedor
`mock` aparece en los logs de Uvicorn.
El login y el registro devuelven `registration_complete=false` y
`requires_phone_verification=true` mientras el teléfono esté pendiente.

El teléfono también puede actualizarse mediante `PATCH /api/v1/users/me`.
Cambiarlo lo marca nuevamente como no verificado y exige repetir el flujo OTP.

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
DATABASE_URL=postgresql+asyncpg://planati:planati@localhost:5433/planati
```

PostgreSQL usa los siguientes valores en el archivo Compose:

- Host: `localhost`
- Puerto: `5433`
- Base: `planati`
- Usuario: `planati`
- Password: `planati`

### JWT, CORS y CSRF

```env
# python -c "import secrets; print(secrets.token_urlsafe(64))"
SECRET_KEY=clave_generada
CORS_ORIGINS=http://localhost:3000,https://tu-dominio.com
CSRF_TRUSTED_ORIGINS=
```

El resto de variables de la fase 2 (zona horaria, mapa, ranking, reseñas, planes,
privacidad) están documentadas con sus valores por defecto en `.env.example`.

### Cloudflare R2

```env
R2_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=tu_access_key
R2_SECRET_ACCESS_KEY=tu_secret_key
R2_BUCKET_NAME=planati-images
R2_PUBLIC_BASE_URL=https://pub-<hash>.r2.dev
```

### Google Maps

El backend no usa ni guarda ninguna clave de Google Maps. La clave pertenece al
frontend (`NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`) y se protege en Google Cloud con
restricciones de dominio y de API. No se debe incluir ninguna clave sensible en el repositorio.

### Copias de seguridad

```env
BACKUP_DIR=backups
BACKUP_KEEP=10
BACKUP_DOCKER_CONTAINER=planati-postgres
```

## Copias de seguridad de la base local

La base del Docker Compose se pierde con `docker compose down -v`, al borrar el
volumen o al reinstalar Docker. `scripts/backup_db.py` guarda copias en `backups/`
(fuera del volumen e ignorada por git, porque contiene datos personales):

```bash
python -m scripts.backup_db create [--tag pre-0010]   # nueva copia (pg_dump dentro del contenedor)
python -m scripts.backup_db list                      # copias con fecha y tamaño
python -m scripts.backup_db restore backups/<archivo>.dump --target planati_restore   # revisar sin tocar la base
python -m scripts.backup_db restore backups/<archivo>.dump   # sobrescribe 'planati' (pide escribir RESTAURAR)
python -m scripts.backup_db prune [--keep 10]         # borra las sin etiqueta más antiguas
```

`create` poda automáticamente: conserva las `BACKUP_KEEP` copias sin etiqueta más
recientes y todas las etiquetadas. Haz una copia:

| Momento | Comando |
|---|---|
| Antes de `python -m alembic upgrade head` | `create --tag pre-<revisión>` |
| Antes de `seed_demo down` o de pruebas destructivas | `create --tag pre-pruebas` |
| Antes de `docker compose down -v` o de reinstalar Docker | `create --tag pre-docker` |
| Si hay datos de prueba que costó crear | `create` semanal |

Copia de vez en cuando la carpeta `backups/` a otro disco o a tu nube personal: si
falla el disco del computador se pierden la base y sus copias a la vez.

## Datos demo (Cúcuta)

```bash
python -m scripts.seed_demo up      # 12 locales en Cúcuta (restaurantes, cafés, bar, hotel, tienda, experiencia)
python -m scripts.seed_demo status
python -m scripts.seed_demo down    # borra solo las cuentas @demo.planati.test y lo asociado
```

Contraseña de las cuentas demo: `Demo12345!`. Los locales se reparten en un radio de
~4 km del centro de Cúcuta, con horarios variados (uno cruza la medianoche y otro no
publica horarios); el último queda `PENDING` para probar la aprobación.

## Funcionalidades y rutas principales

| Requisito | Estado | Implementacion |
|---|---|---|
| Registrar usuarios e iniciar sesion | Parcial | Registro y login implementados; los establecimientos usan autenticacion protegida. |
| Modificar perfil | Cubierto | `PATCH /api/v1/users/me` |
| Actualizar establecimientos | Cubierto | `PATCH /api/v1/establishments/{establishment_id}` |
| Buscar por nombre o categoria | Cubierto | `GET /api/v1/establishments` con `search`, `category`, `establishment_type`, `min_rating`, `sort` (`ranking`, `rating`, `reviews`, `recent`, `name`), `skip` y `limit`. No incluye reseñas: trae `rating_avg`, `rating_count` y `ranking_score`. |
| Visualizar mapa georreferenciado | Cubierto | `GET /api/v1/establishments/map` (marcadores del área visible) y `GET /api/v1/establishments/nearby`; el mapa lo dibuja el frontend. |
| Consultar establecimiento | Cubierto | `GET /api/v1/establishments/{establishment_id}`: catálogo, `rating_distribution`, `category_rank`, las 3 reseñas más recientes (`recent_reviews`) y, para quien consulta, `viewer_review`, `viewer_can_review` y `viewer_review_block`. |
| Publicar resenas y puntuacion | Cubierto | `POST /api/v1/reviews/establishments/{establishment_id}` (una por usuario y local), `GET` paginado de las reseñas de un local, `GET /api/v1/reviews/me`, `PATCH` y `DELETE /api/v1/reviews/{review_id}`. |
| Adjuntar fotografias | Parcial | `POST /api/v1/reviews/upload-url` + `image_urls` al crear o editar (máximo `REVIEW_MAX_IMAGES`, solo URLs de `reviews/` del bucket); falta validar R2 real. |
| Responder resenas | Cubierto | Panel del establecimiento: `GET /api/v1/restaurant/reviews` (filtros `status=all\|unanswered\|answered`, `rating`, `sort`), `GET /api/v1/restaurant/reviews/summary`, `PUT` y `DELETE /api/v1/restaurant/reviews/{review_id}/reply`. El autor recibe una notificación la primera vez que se le responde. |
| Horarios de atencion | Cubierto | `GET` y `PUT /api/v1/restaurant/schedules` (reemplaza todos; hora de Colombia, 0 = lunes; un cierre menor que la apertura cruza la medianoche; máximo 3 tramos por día y sin solapes). |
| Gestion administrativa | Cubierto | Usuarios (listado, detalle, rol, suspender, reactivar, avisos), establecimientos (aprobar, rechazar, suspender, reactivar, editar perfil y catálogo como el establecimiento), moderación de reseñas (bloquear comentario o respuesta, ocultar, restaurar, borrar), reportes y bitácora. |
| Reportes de contenido | Cubierto | `POST /api/v1/reports` (una vez por usuario y destino, límite `REPORTS_PER_DAY_LIMIT`; auto-ocultado opcional con `REPORT_AUTO_HIDE_THRESHOLD`). |
| Planes y recordatorios | Cubierto | `POST/GET /api/v1/plans`, `GET/PATCH/DELETE /api/v1/plans/{id}`, `POST /api/v1/plans/{id}/cancel` y `GET /api/v1/plans/{id}/calendar.ics`. El total se calcula en el servidor; la hora se valida contra los horarios del local (hora de Colombia). El recordatorio llega como notificación en la app (ciclo en segundo plano con `REMINDERS_ENABLED`, o `python -m scripts.run_reminders --once` desde cron) y, al pasar el plan, una invitación a reseñar. |
| Notificaciones en la app | Cubierto | `GET /api/v1/notifications` (paginado), `GET /api/v1/notifications/unread-count`, `POST /api/v1/notifications/{id}/read`, `POST /api/v1/notifications/read-all`, `DELETE /api/v1/notifications/{id}`. Aprobar o rechazar un establecimiento notifica a su dueño. |

### Exportaciones a Excel

| Descarga | Ruta | Alcance |
|---|---|---|
| Menú | `GET /api/v1/restaurant/exports/menu.xlsx` | Productos, combos, composición y enlaces a las imágenes del menú físico del establecimiento autenticado. |
| Reseñas | `GET /api/v1/restaurant/exports/reviews.xlsx` | Reseñas visibles y respuestas del propio establecimiento, con las mismas reglas de moderación del panel. |
| Establecimientos | `GET /api/v1/admin/exports/establishments.xlsx` | Directorio administrativo completo o filtrado por `status` y `search`. |
| Menú de un local (admin) | `GET /api/v1/admin/establishments/{establishment_id}/exports/menu.xlsx` | El mismo archivo de menú para el local seleccionado. |
| Reseñas de un local (admin) | `GET /api/v1/admin/establishments/{establishment_id}/exports/reviews.xlsx` | El mismo archivo de reseñas visibles para el local seleccionado. |

Las rutas de `/restaurant` requieren que el establecimiento esté aprobado. Las rutas de `/admin` requieren rol de administrador. Los archivos contienen encabezados fijos, filtros y fechas en la zona horaria de la aplicación.

### Geolocalizacion

- `GET /api/v1/establishments/nearby?latitude&longitude&radius_km` (radio máximo `NEARBY_MAX_RADIUS_KM`):
  primero filtra en SQL por el cuadrado (*bounding box*) que contiene el círculo de búsqueda y luego
  calcula la distancia exacta con la fórmula haversine solo sobre ese subconjunto. Acepta `category`,
  `establishment_type`, `min_rating` y `sort` (`distance`, `rating` o `relevance`, que mezcla
  ranking y cercanía con `RELEVANCE_RATING_WEIGHT`).
- `GET /api/v1/establishments/map?north&south&east&west`: marcadores del área visible, mejor
  posicionados primero; `truncated=true` si había más de `limit` (máximo `MAP_MAX_MARKERS`).
- Al registrarse, un restaurante envía `latitude` y `longitude` (obligatorias) y opcionalmente
  `location_source` (`GPS`, `ADDRESS`, `MAP_PIN`, `MANUAL`), `google_place_id`, `city` y
  `establishment_type`. La geocodificación ocurre en el frontend; el backend redondea a 6
  decimales y rechaza con `400` los puntos fuera de `SERVICE_AREA_BOUNDS`.
- La ubicación del usuario no se guarda y se omite de los logs de acceso (`app/core/log_filters.py`).

### Puntuación y ranking

Cada establecimiento guarda `rating_count`, `rating_sum`, `rating_avg` y `ranking_score`, que se
recalculan en la misma transacción al crear, editar o borrar una reseña (solo cuentan las
reseñas visibles; bloquear el comentario no cambia el promedio). El ranking es bayesiano:
`(rating_sum + m·C) / (rating_count + m)` con `m = RANKING_MIN_REVIEWS` y `C = RANKING_PRIOR_MEAN`,
para que un local con una sola reseña de 5★ no supere a uno con muchas reseñas buenas. Para
recalcular todo (tras cambiar `m` o `C`, o para corregir derivas): `python -m scripts.recompute_ratings`.

### Almacenamiento de imagenes

- `POST /api/v1/reviews/upload-url?file_extension=.jpg`: URL prefirmada de Cloudflare R2 en la
  carpeta `reviews/` (sin crear antes la reseña); la URL pública va luego en `image_urls`.
- Obsoletas: `POST /api/v1/reviews/{review_id}/images` y `POST /api/v1/reviews/{review_id}/upload-url`.

### Administracion

Todo bajo `/api/v1/admin` y restringido mediante `require_admin`. Cada acción queda en la bitácora
(`GET /admin/moderation-actions`) y notifica al afectado.

- Panel: `GET /admin/dashboard` (incluye pendientes, suspendidos, reportes abiertos, reseñas ocultas,
  comentarios bloqueados y pendientes de revisión).
- Usuarios: `GET /admin/users` (paginado, `search`, `role`, `status`), `GET /admin/users/{id}`,
  `PATCH …/role`, `POST …/suspend`, `POST …/reactivate`, `POST …/notify`. Un usuario suspendido
  recibe `403` con `code: "ACCOUNT_SUSPENDED"` incluso con una sesión abierta.
- Establecimientos: `GET /admin/establishments` (`status=SUSPENDED` incluido), `approve`, `reject`
  (solo pendientes), `suspend`, `reactivate`, `PATCH /admin/establishments/{id}` y el catálogo,
  fotos y horarios en `/admin/establishments/{id}/(products|combos|images|schedules)`.
- Moderación: `GET /admin/reviews`, `POST /admin/reviews/{id}/(block-comment|unblock-comment|hide|restore)`,
  `DELETE /admin/reviews/{id}?reason=`, `POST /admin/review-replies/{id}/(block|unblock)`,
  `DELETE /admin/review-images/{id}?reason=`. Bloquear el comentario muestra en público "El
  comentario fue bloqueado por una violación a las políticas de la aplicación." y conserva las estrellas.
- Reportes: `GET /admin/reports`, `POST /admin/reports/{id}/resolve` (acción `NONE`, `BLOCK_COMMENT`,
  `HIDE_CONTENT`, `DELETE_CONTENT` o `SUSPEND_OWNER`) y `POST /admin/reports/{id}/dismiss`.

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
