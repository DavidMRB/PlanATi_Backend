# Plan Técnico de Backend — Fase 2: Geolocalización, Mapa, Reseñas, Moderación, Notificaciones y Planes (PlanATi)

> **Destinatario de ejecución:** Claude Code (CLI).
> **Ubicación:** `PlanATi_Backend/` (raíz del backend).
> **Documento hermano:** `PlanATi_Frontend/fase2-mapa-resenas-planes-frontend.md`. Las fases de ambos documentos están sincronizadas (B1 ⇄ F1, B2 ⇄ F2, …).
> **Base analizada:** rama `dev`, 2026-11-12, 38 pruebas en verde (`pytest`).
> **Revisión 2 (2026-11-12):** el equipo confirmó como alcance obligatorio: horarios editables, tipo de establecimiento, favoritos, invitación a reseñar después del plan, exportación del plan al calendario (Google Calendar y archivo `.ics` para el celular), protección de la clave de Google Maps, zona horaria de Colombia, datos demo en Cúcuta, aviso de privacidad y autorización de datos (Ley 1581 de 2012) y el **bloqueo del comentario** de una reseña por moderación ("El comentario fue bloqueado por una violación a las políticas de la aplicación.").
> **Revisión 3 (2026-11-12):** se añade la **revisión de seguridad antes de publicar** (sección 9.1–9.5): protección CSRF, cookie solo por HTTPS, clave secreta fuerte y copias de seguridad de la base de datos. Las demás propuestas quedan en la sección 17, "Por planificar".
> **Revisión 4 (2026-11-12):** **el MVP se ejecutará solo en local.** Se implementan ahora (en B0) el CSRF, los atributos centralizados de la cookie, la validación de configuración y una **copia de seguridad local** de PostgreSQL. Todo lo que depende de un servidor publicado (HTTPS, topología de dominios, copias cifradas fuera del equipo, lista de verificación) queda en B9, que se ejecuta solo cuando se decida publicar.

---

## 0. Cómo usar este documento

1. Ejecutar las fases **en orden** (sección 12). Cada fase termina con: migración aplicada (`python -m alembic upgrade head`), `pytest` en verde y la sección correspondiente de la API visible en `/docs`.
2. Respetar todo lo descrito en `CLAUDE.md` (capas, async, mensajes en español, migraciones numeradas a mano, ids de revisión ≤ 32 caracteres, pruebas en SQLite sin pytest-asyncio).
3. Las decisiones marcadas como **[DECISIÓN]** tienen un valor por defecto ya aplicado en este plan; están listadas en la sección 16 por si el equipo decide otra cosa.
4. Los cambios marcados como **[BREAKING ⇄ F*]** modifican la forma de una respuesta que el frontend ya consume. Deben desplegarse junto con la fase del frontend indicada.

---

## 1. Objetivo y alcance

### 1.1 Módulos de esta fase

| Id | Módulo | Resumen |
|---|---|---|
| M1 | **Geolocalización y mapa** | Ubicación del establecimiento por GPS, dirección o pin en el mapa; consulta eficiente de cercanos; consulta por área visible del mapa (viewport). |
| M2 | **Reseñas** | Puntuación de 1 a 5 estrellas obligatoria; comentario e imágenes opcionales; una reseña por usuario y establecimiento, editable y eliminable por su autor. |
| M3 | **Puntuación y posicionamiento** | Agregados de puntuación guardados en el establecimiento, puntuación bayesiana para el ranking, ordenamientos por relevancia, puntuación, cercanía y número de reseñas. |
| M4 | **Respuestas del establecimiento** | El establecimiento (restaurante, hotel, lugar de planes…) responde, edita o borra su respuesta desde su panel. |
| M5 | **Administración y moderación** | Gestión de usuarios (suspender, reactivar, rol), de establecimientos (suspender, reactivar, **editar como si fuera el establecimiento**) y de contenido (**bloquear el comentario** de una reseña o respuesta dejando en su lugar el aviso "El comentario fue bloqueado por una violación a las políticas de la aplicación.", ocultar/restaurar/borrar reseñas e imágenes), reportes de usuarios, normas de la comunidad y bitácora de moderación. |
| M6 | **Notificaciones en la app** | Bandeja de notificaciones por usuario (reseña recibida, respuesta, moderación, aprobación, recordatorios de planes…). |
| M7 | **Planes (agendamiento)** | El usuario agenda una visita: establecimiento, fecha y hora, personas, platos/combos con cantidades, total calculado en el servidor y recordatorio en la app. |
| M8 | **Complementos confirmados** | Horarios editables por el establecimiento (necesarios para validar planes), favoritos, tipo de establecimiento (restaurante, hotel, experiencia…), invitación a reseñar cuando un plan se completa y exportación del plan al calendario (archivo `.ics` con alarma; el enlace de Google Calendar lo arma el frontend). |
| M9 | **Privacidad y datos personales** | Política de tratamiento de datos y términos con versión, autorización expresa al registrarse (Ley 1581 de 2012 y Decreto 1377 de 2013), prueba de esa autorización, nueva aceptación cuando cambia la versión, descarga de los datos propios y eliminación de la cuenta por su titular. |
| M10 | **Seguridad antes de publicar** | Protección CSRF (origen + token por sesión), cookie de sesión solo por HTTPS con una topología de dominios que funcione en producción, clave secreta fuerte validada al arrancar y copias de seguridad de PostgreSQL con prueba de restauración. |

### 1.2 Fuera de alcance (exclusiones)

- **NO** implementar pagos, pedidos ni reservas confirmadas por el establecimiento (ver [DECISIÓN] D1 en la sección 16).
- **NO** enviar recordatorios por SMS, correo ni push nativo en esta fase (solo notificación dentro de la app; Web Push queda como fase opcional B10).
- **NO** migrar a consultas PostGIS obligatorias (queda como fase opcional B10; ver decisión técnica T1).
- **NO** cambiar el valor interno del rol `restaurant` (los textos de la UI pueden decir "establecimiento" o "aliado").
- **NO** borrar físicamente usuarios desde la administración (se suspenden). La eliminación de la cuenta la pide su titular (M9).

---

## 2. Diagnóstico del estado actual

### 2.1 Lo que ya existe y se reutiliza

| Pieza | Dónde | Uso en esta fase |
|---|---|---|
| Coordenadas `latitude`/`longitude` `Numeric(9,6)` | `app/models/establishment.py` | Fuente de verdad de la ubicación. |
| `haversine_km` + bucle de cercanos | `app/services/establishment_service.py` | Se conserva (está citado en `docs_aparte_back/PlanATi_Exposicion_8min.md` para la Guía 6); se le añade un prefiltro SQL. |
| `Review`, `ReviewImage`, `ReviewReply` | `app/models/review.py` | Se extienden (estado, comentario opcional, unicidad, autor). |
| `Schedule` (0 = lunes … 6 = domingo) | `app/models/establishment.py` | Se usa para validar planes; se expone para edición. |
| Servicios de catálogo que reciben el `Establishment` | `app/services/restaurant_service.py` | Se reutilizan tal cual para que el admin edite cualquier establecimiento. |
| URLs prefirmadas de R2 | `app/services/storage.py` | Se añade la carpeta `reviews` sin `review_id` previo. |
| Fixtures `make_client`, `create_user`, `admin_client`, `register_restaurant`, `approved_restaurant` | `tests/conftest.py` | Base para las pruebas nuevas. |

### 2.2 Hallazgos (errores y carencias que este plan corrige)

**Reseñas (errores reales):**

1. `POST /reviews/establishments/{id}` no comprueba `status == "APPROVED"`: se puede reseñar un establecimiento pendiente, rechazado o suspendido. `GET /reviews/establishments/{id}` tampoco filtra.
2. Las cuentas `restaurant` nacen con `phone_verified=True` y `status="ACTIVE"` (`app/services/auth_service.py:74-75`), así que pasan `require_active_user` y **pueden reseñar, incluso su propio establecimiento**. El admin también puede.
3. No hay unicidad usuario–establecimiento: un mismo usuario puede publicar reseñas ilimitadas e inflar o hundir la puntuación.
4. Responder dos veces la misma reseña (`POST /reviews/{id}/reply`) choca con `unique=True` de `review_replies.review_id` → `IntegrityError` → **500**.
5. `comment` es obligatorio (`min_length=1`, `NOT NULL`); el requisito lo hace opcional.
6. `image_urls` acepta cualquier cadena: no valida que sea una URL de nuestro bucket ni limita la cantidad.
7. Subir una imagen exige crear antes la reseña (`/reviews/{review_id}/upload-url`): flujo en dos pasos innecesario.
8. `ReviewResponse` no trae autor (apodo/foto); el frontend muestra "Comensal de PlanATi".
9. No existe editar ni eliminar reseña, ni paginación, ni orden, ni `CHECK` de 1 a 5 en la base de datos.

**Rendimiento del directorio:**

10. `GET /establishments` y `GET /establishments/nearby` cargan `_DETAIL_LOAD_OPTIONS` (menú, combos, imágenes, **todas las reseñas y sus imágenes**) para cada establecimiento y las devuelven en el JSON. El frontend calcula el promedio desde ese arreglo. Con volumen real esto crece sin límite.
11. `/nearby` recorre en Python **todos** los establecimientos aprobados. No hay consulta por viewport para el mapa ni paginación en el directorio.

**Geolocalización:**

12. `RestaurantRegisterRequest` no recibe coordenadas: un restaurante nuevo nace sin ubicación y **no aparece en el mapa ni en cercanos** hasta que la edite a mano en su perfil.
13. No se guarda cómo se obtuvo la ubicación (GPS, dirección, pin) ni el `place_id` de Google.

**Administración:**

14. La suspensión de un establecimiento aprobado reutiliza `REJECTED` (`reject_establishment`), lo que mezcla "solicitud rechazada" con "suspendido" y habilita `PATCH /restaurant/reapply` para un local suspendido.
15. `PATCH /admin/users/{id}/role` permite que un admin se quite su propio rol (y dejar el sistema sin administradores).
16. No hay suspensión de usuarios, moderación de contenido, reportes, bitácora ni forma de notificar al afectado.
17. `GET /admin/users` no tiene paginación ni filtros.

**Otros:**

18. No existen notificaciones (la campana del frontend es decorativa), ni planes, ni tareas en segundo plano.
19. El restaurante no puede editar sus horarios desde `/restaurant` (`RestaurantProfileUpdate` no incluye `schedules`).
20. No hay zona horaria de la aplicación. En Windows, `zoneinfo.ZoneInfo("America/Bogota")` falla sin el paquete `tzdata`.
21. `scripts/seed_demo.py` ubica los restaurantes demo en Bogotá (`BASE_LAT 4.711`), pero el producto está enfocado en Cúcuta.
22. `README.md` documenta `GOOGLE_MAPS_API_KEY` en el backend, pero el backend no la usa; pertenece al frontend.
23. No hay política de tratamiento de datos, términos ni normas de la comunidad, y no se guarda la autorización del titular al crear la cuenta (lo exige la Ley 1581 de 2012). Tampoco se pueden descargar los datos propios ni eliminar la cuenta.
24. Las cuentas creadas con Google reciben una contraseña aleatoria (`auth_service.py:180`), así que no pueden confirmar acciones sensibles (como eliminar la cuenta) con contraseña: se usará un código SMS.

**Seguridad (revisión antes de publicar):**

25. **No hay protección CSRF.** `GUIA_AUTENTICACION_COOKIE_HTTPONLY.md` (sección 7) la deja pendiente. Hoy solo mitigan `SameSite=lax` y el *preflight* de CORS para JSON.
26. `secret_key` tiene el valor por defecto `"development-secret"` en `app/core/config.py` y nada impide arrancar en producción con él (con esa clave cualquiera puede firmar un JWT de admin).
27. La cookie de sesión ya se marca `Secure` cuando `APP_ENV=production` (`app/core/security.py`), pero `clear_auth_cookie` no repite los atributos y la cookie `oauth_state` se configura aparte (`app/api/routes/auth.py`).
28. `proxy.ts` del frontend comprueba la cookie en el dominio del frontend. En local funciona porque `localhost:3000` y `localhost:8000` comparten cookies; **en producción, con la API en otro subdominio y sin atributo `Domain`, el frontend no vería la cookie** y enviaría a todos al login.
29. Nada impide arrancar en producción con `SMS_PROVIDER=mock` (escribe los códigos OTP en los logs), con las credenciales de PostgreSQL del Compose (`planati`/`planati`) o con `/docs` expuesto.
30. No existen copias de seguridad de la base de datos ni un procedimiento de restauración.

**Bien resuelto (verificado):** `.env` está en `.gitignore` y nunca se subió a git; solo se versiona `.env.example`.

---

## 3. Convenciones a respetar

- **Capas:** `routes` (HTTP, códigos) → `services` (lógica, `AsyncSession` como primer argumento) → `models`. Errores de dominio como excepciones propias (`ReviewError`, `PlanValidationError`, …) que la ruta traduce a `HTTPException`.
- **Transacciones:** las funciones `notify(...)`, `record_moderation_action(...)` y `recalculate_establishment_rating(...)` **no hacen commit**; se ejecutan dentro de la transacción de la operación principal, que hace un único `commit()` al final. Así la reseña, el promedio y la notificación quedan consistentes.
- **Aislamiento (IDOR):** toda consulta bajo `/restaurant` filtra por el establecimiento del propietario; toda consulta bajo `/plans`, `/notifications`, `/favorites` y edición de reseñas filtra por `user_id` del usuario autenticado. Un recurso ajeno responde **404**, no 403.
- **Paginación** en endpoints nuevos con un esquema genérico (`app/schemas/common.py`):
  ```python
  class Page(BaseModel, Generic[T]):
      items: list[T]
      total: int
      skip: int
      limit: int
  ```
- **Fechas:** guardar y filtrar **siempre en UTC con zona** (`DateTime(timezone=True)`). SQLite descarta el offset al guardar, así que hay que convertir a UTC antes de persistir o comparar, y normalizar al leer (como ya hace `phone_verification_service.py:69`). Crear `app/core/time.py`:
  ```python
  UTC = timezone.utc
  LOCAL_TZ = ZoneInfo(settings.app_timezone)  # America/Bogota

  def utcnow() -> datetime: ...
  def ensure_utc(value: datetime) -> datetime:  # naive => se asume UTC; aware => astimezone(UTC)
  def to_local(value: datetime) -> datetime:    # para validar contra horarios locales
  ```
- **Strings de usuario** en español. Nombres de código en inglés como el resto del proyecto.

---

## 4. Decisiones técnicas

| Id | Decisión | Motivo |
|---|---|---|
| T1 | **Geodatos portables:** `latitude`/`longitude` siguen siendo la fuente de verdad. Prefiltro por *bounding box* en SQL (funciona en SQLite y PostgreSQL) + `haversine_km` en Python solo sobre el subconjunto. Índice compuesto `(latitude, longitude)`. | Las pruebas corren en SQLite (sin PostGIS) y el bucle haversine forma parte de la exposición del curso. Rinde bien hasta miles de establecimientos. PostGIS (`geography(Point,4326)` + GIST + `ST_DWithin`) queda en B10. |
| T2 | **La geocodificación ocurre en el frontend** (Google Places/Geocoding con la clave de navegador). El backend valida y guarda coordenadas, `google_place_id`, `location_source` y `city`. | El backend no necesita clave de Google ni costo por llamadas. |
| T3 | **Agregados denormalizados** en `establishments` (`rating_count`, `rating_sum`, `rating_avg`, `ranking_score`), recalculados con una consulta `COUNT/SUM` en la misma transacción de cada cambio de reseña. | Directorio y mapa ordenan e informan sin cargar reseñas. Recalcular (en vez de sumar/restar) evita derivas. |
| T4 | **Ranking bayesiano** con prior configurable (sección 8). | Un local con una sola reseña de 5★ no debe superar a uno con 40 reseñas de 4,6★. |
| T5 | **Moderación por estado** (`VISIBLE`/`HIDDEN`) en reseñas y respuestas; bitácora `moderation_actions` con motivo y metadatos. | Reversible y auditable. |
| T6 | **Notificaciones en tabla + consulta periódica (polling)** desde el frontend. Clave `dedupe_key` única para evitar duplicados. | Simple, sin infraestructura extra; Web Push opcional en B10. |
| T7 | **Recordatorios con un ciclo asíncrono dentro del proceso** (lifespan de FastAPI) que llama a un servicio **idempotente**; alternativa por cron con `scripts/run_reminders.py`. | Sin Redis/Celery. La idempotencia permite varios workers. |
| T8 | **Nuevo estado `SUSPENDED`** para establecimientos y usuarios. | Separa rechazo de solicitud y sanción. |
| T9 | **Bloquear el comentario no es lo mismo que ocultar la reseña.** El bloqueo (`comment_status=BLOCKED`) sustituye el texto en público por un aviso fijo y conserva la reseña, su autor y sus estrellas, que siguen contando en el promedio. Ocultar (`status=HIDDEN`) retira la reseña entera y la saca del promedio (spam, reseñas falsas). | En el caso típico (insultos, datos personales de terceros) la calificación es legítima y solo sobra el texto. |
| T10 | **Versiones legales en configuración** (`PRIVACY_POLICY_VERSION`, `TERMS_VERSION`). La aceptación se guarda en una tabla de historial (prueba de la autorización) y se copia en columnas de `users`. | Comprobar el consentimiento en cada petición cuesta solo comparar dos columnas. |

---

## 5. Modelo de datos

### 5.1 `Establishment` (modificar `app/models/establishment.py`)

Columnas nuevas:

```python
ESTABLISHMENT_STATUSES = {"PENDING", "APPROVED", "REJECTED", "SUSPENDED"}
LOCATION_SOURCES = {"GPS", "ADDRESS", "MAP_PIN", "MANUAL"}
ESTABLISHMENT_TYPES = {"RESTAURANT", "CAFE", "BAR", "HOTEL", "EXPERIENCE", "STORE", "OTHER"}

location_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
google_place_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
city: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
establishment_type: Mapped[str] = mapped_column(String(30), default="RESTAURANT", server_default="RESTAURANT", nullable=False, index=True)
suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

rating_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
rating_sum: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
rating_avg: Mapped[float | None] = mapped_column(Float, nullable=True)
ranking_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
```

Índices: `ix_establishments_lat_lng (latitude, longitude)`.

> `establishment_type` responde a que la plataforma no solo tendrá restaurantes sino hoteles y lugares que ofrecen productos o planes. `category` sigue siendo texto libre (p. ej. "Parrilla y Asados") dentro de un tipo.

### 5.2 `User` (modificar `app/models/user.py`)

- `status` admite además `SUSPENDED`.
- `suspension_reason: Text | None`, `suspended_at: DateTime(timezone=True) | None`.
- Relación `reviews` (back_populates con `Review.author`).
- `privacy_policy_version: String(20) | None`, `terms_version: String(20) | None`, `consents_updated_at: DateTime(timezone=True) | None`: copia de la última aceptación (el historial está en `consents`, sección 5.9).
- (B8) `status` admite `DELETED` (lápida anonimizada de una cuenta eliminada, ver 7.9); `deleted_at` y `last_data_export_at: DateTime(timezone=True) | None`. Propiedad `pending_consents`.
- (B8) `phone_verification_codes.purpose`: `VERIFY_PHONE` | `DELETE_ACCOUNT` (un código de verificación no sirve para eliminar la cuenta).

### 5.3 `Review`, `ReviewImage`, `ReviewReply` (modificar `app/models/review.py`)

```python
REVIEW_STATUSES = {"VISIBLE", "HIDDEN"}          # la reseña completa
COMMENT_STATUSES = {"VISIBLE", "BLOCKED"}        # solo el texto (y opcionalmente las imágenes)
BLOCKED_COMMENT_NOTICE = "El comentario fue bloqueado por una violación a las políticas de la aplicación."
BLOCKED_REPLY_NOTICE = "La respuesta fue bloqueada por una violación a las políticas de la aplicación."

class Review(Base):
    __table_args__ = (
        UniqueConstraint("user_id", "establishment_id", name="uq_reviews_user_establishment"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
        Index("ix_reviews_establishment_status_created", "establishment_id", "status", "created_at"),
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)        # ahora opcional
    status: Mapped[str] = mapped_column(String(20), default="VISIBLE", server_default="VISIBLE", nullable=False)
    comment_status: Mapped[str] = mapped_column(String(20), default="VISIBLE", server_default="VISIBLE", nullable=False)
    moderation_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    moderation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)   # nota del admin para el autor
    flagged_for_review: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.false(), nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    author: Mapped["User"] = relationship(back_populates="reviews")

class ReviewImage(Base):
    display_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

class ReviewReply(Base):
    comment_status: Mapped[str] = mapped_column(String(20), default="VISIBLE", server_default="VISIBLE", nullable=False)
    moderation_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    moderation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    flagged_for_review: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa.false(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
```

**Reglas del bloqueo de comentarios:**

- El texto original **se conserva** en la base de datos (para apelaciones y auditoría), pero nunca se devuelve en respuestas públicas ni al panel del establecimiento: llega `comment: null`, `comment_blocked: true` y `moderation_notice` con el aviso fijo.
- Solo el autor (en `GET /reviews/me` y en `viewer_review` del detalle) y los admins ven el texto original, la categoría y la nota de moderación.
- Las estrellas siguen contando en el promedio: bloquear o desbloquear **no** recalcula agregados.
- Si el autor reescribe un comentario bloqueado, el texto nuevo se guarda pero **sigue bloqueado** y queda `flagged_for_review=True` hasta que un admin lo revise. Así no se puede esquivar la moderación editando.
- Lo mismo vale para la respuesta del establecimiento (`BLOCKED_REPLY_NOTICE`).

**Categorías de moderación** (`MODERATION_CATEGORIES`; deben coincidir con las secciones de las normas de la comunidad del frontend):

| Código | Etiqueta |
|---|---|
| `OFFENSIVE_LANGUAGE` | Lenguaje ofensivo o insultos |
| `HATE_OR_DISCRIMINATION` | Discriminación o discurso de odio |
| `PERSONAL_DATA` | Datos personales de terceros |
| `SPAM_OR_ADVERTISING` | Spam o publicidad |
| `FALSE_OR_MISLEADING` | Información falsa o engañosa |
| `SEXUAL_OR_VIOLENT` | Contenido sexual o violento |
| `ILLEGAL_CONTENT` | Contenido ilegal |
| `OFF_TOPIC` | No relacionado con el lugar |
| `OTHER` | Otro motivo |

### 5.4 `Report` (nuevo, `app/models/report.py`)

```python
REPORT_TARGETS = {"REVIEW", "REVIEW_REPLY", "REVIEW_IMAGE", "ESTABLISHMENT", "ESTABLISHMENT_IMAGE", "MENU_ITEM", "USER"}
REPORT_REASONS = {"SPAM", "OFFENSIVE", "FALSE_INFO", "INAPPROPRIATE_IMAGE", "OTHER"}
REPORT_STATUSES = {"OPEN", "RESOLVED", "DISMISSED"}

class Report(Base):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("reporter_id", "target_type", "target_id", name="uq_reports_reporter_target"),
                      Index("ix_reports_status_target", "status", "target_type", "target_id"))
    id; reporter_id (FK users, CASCADE); target_type (String 30); target_id (Integer)
    reason (String 30); details (Text | None)
    status (String 20, default OPEN); resolved_by_id (FK users, SET NULL | None)
    resolution_note (Text | None); created_at; resolved_at (| None)
```

El destino es polimórfico (sin FK); `report_service.resolve_target()` valida que exista.

### 5.5 `ModerationAction` (nuevo, `app/models/moderation.py`)

```python
class ModerationAction(Base):
    __tablename__ = "moderation_actions"
    id; admin_id (FK users, SET NULL | None)
    action (String 40)       # HIDE_REVIEW, RESTORE_REVIEW, DELETE_REVIEW, BLOCK_COMMENT, UNBLOCK_COMMENT,
                             # BLOCK_REPLY, UNBLOCK_REPLY, DELETE_REVIEW_IMAGE, DELETE_ESTABLISHMENT_IMAGE,
                             # SUSPEND_USER, REACTIVATE_USER,
                             # CHANGE_ROLE, SUSPEND_ESTABLISHMENT, REACTIVATE_ESTABLISHMENT,
                             # EDIT_ESTABLISHMENT, EDIT_CATALOG, RESOLVE_REPORT, DISMISS_REPORT, NOTIFY_USER
    target_type (String 30); target_id (Integer)
    reason (Text | None); details (JSON | None)   # p. ej. snapshot del contenido borrado o valores antes/después
    created_at
```

`sqlalchemy.JSON` funciona en SQLite y PostgreSQL.

### 5.6 `Notification` (nuevo, `app/models/notification.py`)

```python
class NotificationType(StrEnum):
    REVIEW_RECEIVED = "REVIEW_RECEIVED"            # al dueño del establecimiento
    REVIEW_REPLIED = "REVIEW_REPLIED"              # al autor de la reseña
    REVIEW_PROMPT = "REVIEW_PROMPT"                # tras un plan completado: "¿Cómo te fue?"
    CONTENT_MODERATED = "CONTENT_MODERATED"        # contenido oculto/borrado por moderación
    CONTENT_RESTORED = "CONTENT_RESTORED"
    ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"
    ACCOUNT_REACTIVATED = "ACCOUNT_REACTIVATED"
    ESTABLISHMENT_APPROVED = "ESTABLISHMENT_APPROVED"
    ESTABLISHMENT_REJECTED = "ESTABLISHMENT_REJECTED"
    ESTABLISHMENT_SUSPENDED = "ESTABLISHMENT_SUSPENDED"
    ESTABLISHMENT_REACTIVATED = "ESTABLISHMENT_REACTIVATED"
    ESTABLISHMENT_EDITED_BY_ADMIN = "ESTABLISHMENT_EDITED_BY_ADMIN"
    PLAN_REMINDER = "PLAN_REMINDER"
    PLAN_AFFECTED = "PLAN_AFFECTED"                # el establecimiento del plan fue suspendido
    REPORT_RESOLVED = "REPORT_RESOLVED"            # al usuario que reportó
    ADMIN_REPORT_OPENED = "ADMIN_REPORT_OPENED"    # a los admins
    ADMIN_MESSAGE = "ADMIN_MESSAGE"                # aviso manual del admin

class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read_created", "user_id", "read_at", "created_at"),)
    id; user_id (FK users, CASCADE, index)
    type (String 40); title (String 150); body (Text)
    link (String 300 | None)          # ruta relativa del frontend, p. ej. "/plans/12"
    data (JSON | None)                # ids auxiliares (plan_id, review_id, establishment_id…)
    dedupe_key (String 150 | None, unique)
    read_at (| None); created_at
```

### 5.7 `Plan` y `PlanItem` (nuevo, `app/models/plan.py`)

```python
PLAN_STATUSES = {"SCHEDULED", "CANCELLED", "COMPLETED"}

class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (Index("ix_plans_user_scheduled", "user_id", "scheduled_at"),
                      Index("ix_plans_reminder_due", "status", "reminder_at", "reminder_sent_at"))
    id; user_id (FK users, CASCADE); establishment_id (FK establishments, CASCADE)
    title (String 120 | None)               # por defecto "Plan en {nombre}"
    scheduled_at (DateTime tz, NOT NULL)    # UTC
    party_size (Integer, default 1)         # 1..50
    notes (Text | None)
    status (String 20, default SCHEDULED)
    reminder_minutes_before (Integer | None)  # None = sin recordatorio
    reminder_at (DateTime tz | None)          # scheduled_at - reminder_minutes_before
    reminder_sent_at (DateTime tz | None)
    total_amount (Numeric(12,2), default 0)   # calculado en el servidor
    currency (String 3, default "COP")
    created_at; updated_at
    items: relationship(PlanItem, cascade="all, delete-orphan", lazy="selectin")
    establishment: relationship(lazy="joined")

class PlanItem(Base):
    __tablename__ = "plan_items"
    id; plan_id (FK plans, CASCADE, index)
    menu_item_id (FK menu_items, SET NULL | None)   # el restaurante puede borrar el producto
    name_snapshot (String 120); unit_price_snapshot (Numeric(10,2))
    quantity (Integer)                               # 1..99
    notes (String 200 | None)                        # "sin cebolla"
```

Los *snapshots* congelan nombre y precio al momento de planear: si el restaurante cambia el precio o borra el producto, el plan sigue siendo legible y el total no cambia sin que el usuario lo sepa.

### 5.8 `Favorite` (nuevo, `app/models/favorite.py`)

`favorites (user_id FK CASCADE, establishment_id FK CASCADE, created_at)` con `UniqueConstraint(user_id, establishment_id)`. Los diseños ya tienen "Mis Favoritos" como sección pendiente.

### 5.9 `Consent` y `DataRequest` (nuevos, `app/models/privacy.py`)

```python
CONSENT_DOCUMENTS = {"PRIVACY_POLICY", "TERMS"}   # las normas de la comunidad forman parte de los términos
CONSENT_CHANNELS = {"WEB_REGISTER", "GOOGLE_COMPLETE_PROFILE", "RESTAURANT_REGISTER", "RE_ACCEPTANCE"}

class Consent(Base):
    """Prueba de la autorización del titular (Decreto 1377 de 2013)."""
    __tablename__ = "consents"
    id; user_id (FK users, CASCADE, index)
    document (String 30); version (String 20); channel (String 30)
    accepted_at (DateTime tz)
    ip_address (String 45 | None); user_agent (String 255 | None)

DATA_REQUEST_TYPES = {"CONSULTA", "ACTUALIZACION", "RECTIFICACION", "SUPRESION", "REVOCATORIA", "RECLAMO"}

class DataRequest(Base):
    """Solicitudes de los titulares (opcional dentro de B8; ver 7.9)."""
    __tablename__ = "data_requests"
    id; user_id (FK users, SET NULL | None); contact_email (String 255)
    request_type (String 20); description (Text)
    status (String 20, default OPEN)      # OPEN, IN_PROGRESS, RESOLVED, REJECTED
    due_at (DateTime tz)                  # consultas: 10 días hábiles; reclamos: 15 (arts. 14 y 15, Ley 1581)
    response (Text | None); resolved_by_id (FK users, SET NULL | None)
    created_at; resolved_at (| None)
```

### 5.10 Registro de modelos

Importar `Report`, `ModerationAction`, `Notification`, `Plan`, `PlanItem`, `Favorite`, `Consent` y `DataRequest` en `app/models/__init__.py` (y en `__all__`), para que `Base.metadata` los vea en Alembic y en `create_all` de las pruebas.

---

## 6. Migraciones (Alembic)

Numeradas a mano, id de revisión ≤ 32 caracteres, una por fase:

| Archivo | `revision` | Contenido |
|---|---|---|
| `0008_notifications.py` | `0008_notifications` | Tabla `notifications`. |
| `0009_establishment_geo.py` | `0009_establishment_geo` | `location_source`, `google_place_id`, `city`, `establishment_type`, índice `(latitude, longitude)`. |
| `0010_reviews_rating.py` | `0010_reviews_rating` | *(Los agregados `rating_*` y `ranking_score` con su backfill se adelantaron a `0009`.)* `comment` nullable; `status`, `comment_status`, `moderation_category`, `moderation_reason`, `flagged_for_review`, `edited_at` en `reviews`; **eliminar duplicados** (ver abajo) y crear `uq_reviews_user_establishment`; `ck_reviews_rating_range`; índice compuesto; `display_order` en `review_images`; `comment_status`, `moderation_category`, `moderation_reason`, `flagged_for_review`, `updated_at` en `review_replies`; `rating_count`, `rating_sum`, `rating_avg`, `ranking_score` en `establishments` + **backfill**. |
| `0011_moderation.py` | `0011_moderation` | `suspension_reason`, `suspended_at` en `users`; `suspension_reason` en `establishments`; tablas `reports` y `moderation_actions`. |
| `0012_plans.py` | `0012_plans` | Tablas `plans` y `plan_items`. |
| `0013_favorites.py` | `0013_favorites` | Tabla `favorites`. |
| `0014_privacy.py` | `0014_privacy` | `privacy_policy_version`, `terms_version`, `consents_updated_at`, `last_data_export_at` y `deleted_at` en `users`; `purpose` en `phone_verification_codes`; tabla `consents` (`data_requests` no se creó: era opcional). Las cuentas existentes quedan sin versión aceptada y se les pedirá aceptar al entrar. |

**Antes de aplicar cada migración** en la base local: `python -m scripts.backup_db create --tag pre-<revisión>` (9.4.1). Es especialmente importante en `0010`, que borra filas.

**Duplicados de reseñas (0010).** Antes de crear la restricción única, conservar la reseña más reciente por `(user_id, establishment_id)`:

```sql
DELETE FROM reviews r USING reviews r2
WHERE r.user_id = r2.user_id AND r.establishment_id = r2.establishment_id AND r.id < r2.id;
```

Documentarlo en el docstring de la migración. El seed actual usa `rng.sample`, así que no genera duplicados; esto protege datos creados a mano.

**Backfill de agregados (0010).** Con `ranking_score = (rating_sum + m·C) / (rating_count + m)` (sección 8):

```sql
UPDATE establishments e
SET rating_count = s.c, rating_sum = s.s, rating_avg = s.s::float / s.c
FROM (SELECT establishment_id, COUNT(*) c, SUM(rating) s FROM reviews GROUP BY establishment_id) s
WHERE s.establishment_id = e.id;

UPDATE establishments SET ranking_score = (rating_sum + :m * :c) / (rating_count + :m);
```

Usar los valores por defecto de la configuración (`m=5`, `C=3.5`). Además crear `scripts/recompute_ratings.py` que recalcula todo desde cero (sirve para corregir derivas y tras cambiar `m` o `C`).

`downgrade()` de cada migración debe revertir sus cambios (la de duplicados no puede restaurar filas borradas; indicarlo en un comentario).

---

## 7. Contratos de API

Todas las rutas cuelgan de `/api/v1`. Códigos de error en español en `detail`.

### 7.1 Geolocalización y mapa (B2)

#### `GET /establishments/nearby` (modificar)

| Parámetro | Tipo | Regla |
|---|---|---|
| `latitude`, `longitude` | float | obligatorios, rangos válidos |
| `radius_km` | float | `> 0`, `≤ NEARBY_MAX_RADIUS_KM` (50); por defecto 5 |
| `limit` | int | 1..50; por defecto 20 |
| `category`, `establishment_type` | str | opcionales |
| `min_rating` | float | opcional, 1..5 (compara contra `rating_avg`) |
| `sort` | `distance` \| `rating` \| `relevance` | por defecto `distance` |

Respuesta: `list[EstablishmentNearbyItem]` = `EstablishmentListItem` + `distance_km`.

Implementación en `establishment_service.list_nearby_establishments`:

```python
def bounding_box(lat: float, lng: float, radius_km: float) -> tuple[float, float, float, float]:
    delta_lat = radius_km / 111.32
    delta_lng = radius_km / (111.32 * max(math.cos(math.radians(lat)), 0.01))
    return lat - delta_lat, lat + delta_lat, lng - delta_lng, lng + delta_lng
```

1. Consulta SQL: `APPROVED`, coordenadas no nulas, `latitude BETWEEN south AND north`, `longitude BETWEEN west AND east`, filtros opcionales. **Sin** cargar reseñas.
2. Bucle actual con `haversine_km` sobre ese subconjunto (se conserva el `for`/`continue`/`if` citado en la exposición; si cambian los números de línea, actualizar `docs_aparte_back/PlanATi_Exposicion_8min.md`).
3. Ordenar según `sort` y cortar en `limit`.

No se cruza el antimeridiano (Colombia), así que no hace falta tratarlo; dejarlo comentado.

#### `GET /establishments/map` (nuevo)

Marcadores del área visible del mapa.

| Parámetro | Regla |
|---|---|
| `north`, `south`, `east`, `west` | obligatorios; `south < north` y `west < east` (si no, 400) |
| `category`, `establishment_type`, `min_rating` | opcionales |
| `limit` | 1..`MAP_MAX_MARKERS` (500); por defecto 300 |

Respuesta:

```json
{
  "items": [
    {"id": 3, "name": "Parrilla A", "category": "Parrilla", "establishment_type": "RESTAURANT",
     "latitude": "7.889100", "longitude": "-72.496700", "rating_avg": 4.4, "rating_count": 18,
     "price_range": "$$", "profile_image_url": "https://…"}
  ],
  "truncated": false
}
```

Ordenado por `ranking_score DESC` antes de aplicar `limit`, para que al truncar queden los mejores. `truncated = total > limit`.

#### `GET /establishments` (modificar) — **[BREAKING ⇄ F2]**

- Parámetros nuevos: `sort` (`ranking` por defecto \| `rating` \| `reviews` \| `recent` \| `name`), `establishment_type`, `min_rating`, `skip` (≥ 0), `limit` (1..50, por defecto 20).
- `response_model=list[EstablishmentListItem]`: **deja de incluir `reviews`**; añade `rating_avg`, `rating_count`, `ranking_score`, `establishment_type`, `city`. Conserva `menu_items` y `schedules` de momento, porque la página de inicio arma "experiencias" con los combos del listado (marcar `menu_items` como pendiente de sustituir por un endpoint de combos destacados).
- La consulta del listado ya **no** usa `_DETAIL_LOAD_OPTIONS`: crear `_LIST_LOAD_OPTIONS` sin reseñas.

#### `GET /establishments/{id}` (modificar) — **[BREAKING ⇄ F2/F3]**

`EstablishmentDetailResponse` cambia así:

| Campo | Cambio |
|---|---|
| `reviews` | **Se elimina**. Sustituido por `recent_reviews` (las 3 visibles más recientes, con autor). La lista completa sale del endpoint paginado. |
| `average_rating`, `reviews_count` | Se mantienen (ahora leen `rating_avg` y `rating_count`). |
| `rating_distribution` | Nuevo: `{"1": n, "2": n, "3": n, "4": n, "5": n}` (solo visibles). |
| `ranking_score`, `category_rank` | Nuevo. `category_rank` = posición del local entre los aprobados de su misma categoría por `ranking_score` (1 + cantidad con puntaje mayor). |
| `viewer_review` | Nuevo: la reseña del usuario que consulta, en cualquier estado (para ver si fue ocultada), o `null`. |
| `viewer_can_review` / `viewer_review_block` | Nuevo: `true`/`false` y motivo (`LOGIN_REQUIRED`, `PHONE_NOT_VERIFIED`, `ROLE_NOT_ALLOWED`, `OWNER`, `ALREADY_REVIEWED`, `SUSPENDED`). |
| `is_favorite` | Nuevo (B7); `false` sin sesión. |
| `location_source`, `google_place_id`, `city`, `establishment_type` | Nuevos. |

#### Ubicación al registrar y editar

- `POST /auth/restaurant/register` (modificar): añadir `latitude` y `longitude` **obligatorios** **[DECISIÓN D3]**, y opcionales `location_source`, `google_place_id`, `city`, `establishment_type`. Actualizar `restaurant_payload()` en `tests/conftest.py`.
- `PATCH /restaurant/profile` y `PATCH /restaurant/reapply` (modificar): aceptar los mismos campos.
- Validaciones comunes (un `model_validator` reutilizable en `app/schemas/restaurant.py`):
  - `latitude` y `longitude` se envían **juntas o ninguna** → 422.
  - Si `SERVICE_AREA_BOUNDS` está configurado y el punto cae fuera → 400 "La ubicación está fuera del área de servicio de PlanATi."
  - `location_source` ∈ `LOCATION_SOURCES`.
- `POST /admin/establishments/{id}/approve`: si el local no tiene coordenadas, aprobar igualmente pero devolver `warnings: ["El establecimiento no tiene ubicación y no aparecerá en el mapa."]` en `EstablishmentDecisionResponse` (campo nuevo, lista vacía por defecto).

### 7.2 Reseñas — usuario (B3)

**Quién puede reseñar** (`review_service.check_can_review`, reutilizado por el detalle para `viewer_can_review`):
rol `user` + `ACTIVE` + `phone_verified`; establecimiento `APPROVED`; el usuario no es su dueño (`owner_id`, cubre establecimientos legados creados con `POST /establishments`); no tiene ya una reseña ahí; no superó `REVIEWS_PER_DAY_LIMIT`.

#### `POST /reviews/upload-url?file_extension=.jpg` (nuevo)

Devuelve `UploadUrlResponse` en la carpeta `reviews/`. Requiere poder reseñar (rol `user` activo). Sustituye a `POST /reviews/{review_id}/upload-url`, que se marca `deprecated=True` y se elimina cuando el frontend migre (el frontend actual no lo usa).

#### `POST /reviews/establishments/{establishment_id}` (modificar)

```json
{ "rating": 4, "comment": "Muy buen servicio", "image_urls": ["https://pub-…/reviews/uuid.jpg"] }
```

| Regla | Error |
|---|---|
| `rating` entero 1..5 obligatorio | 422 |
| `comment` opcional, `strip()`, vacío → `null`, máx. `REVIEW_COMMENT_MAX_LENGTH` (2000) | 422 |
| `image_urls` máx. `REVIEW_MAX_IMAGES` (5), sin repetidas, cada una debe empezar por `f"{R2_PUBLIC_BASE_URL}/reviews/"` | 422 |
| Establecimiento inexistente o no `APPROVED` | 404 |
| Rol no permitido, teléfono sin verificar, cuenta suspendida o dueño | 403 |
| Ya existe una reseña del usuario | 409 con `{"detail": "Ya reseñaste este lugar. Puedes editar tu reseña.", "review_id": n}` |
| Límite diario superado | 429 |

Efectos en la misma transacción: crear reseña e imágenes → `recalculate_establishment_rating` → `notify(owner, REVIEW_RECEIVED, link="/restaurant/reviews")` → `commit`. Respuesta `201` con `ReviewPublic`.

#### `GET /reviews/establishments/{establishment_id}` (modificar)

Parámetros: `sort` (`recent` por defecto \| `rating_desc` \| `rating_asc`), `rating` (1..5, filtra), `with_photos` (bool), `skip`, `limit` (1..50, por defecto 10).
Respuesta: `Page[ReviewPublic]`. Solo reseñas `VISIBLE` de establecimientos `APPROVED` (404 en otro caso). Las respuestas `HIDDEN` del establecimiento no se incluyen.

```python
class ReviewAuthor(BaseModel):
    id: int
    display_name: str        # nickname, o primer nombre + inicial ("Laura G."); nunca email ni teléfono
    picture: str | None

class ReviewReplyPublic(BaseModel):
    id: int; created_at: datetime; updated_at: datetime
    comment: str | None                    # null si está bloqueada
    comment_blocked: bool
    moderation_notice: str | None          # BLOCKED_REPLY_NOTICE si está bloqueada

class ReviewPublic(BaseModel):
    id: int; establishment_id: int; rating: int
    comment: str | None                    # null si no escribió texto o si está bloqueado
    comment_blocked: bool
    moderation_notice: str | None          # BLOCKED_COMMENT_NOTICE si está bloqueado
    created_at: datetime; edited_at: datetime | None; status: str
    author: ReviewAuthor
    images: list[ReviewImageResponse]
    reply: ReviewReplyPublic | None
```

La conversión de modelo a esquema público se hace en una sola función (`to_public_review`) para que ninguna ruta filtre por error el texto bloqueado. `MyReview` (vista del autor) añade el texto original, `comment_status`, `moderation_category`, `moderation_reason` y `flagged_for_review`.

#### `GET /reviews/me` (nuevo)

`Page[MyReview]` con todas las reseñas del usuario (incluidas las ocultas, con `moderation_reason`) y `establishment: {id, name, profile_image_url}`.

#### `PATCH /reviews/{review_id}` (nuevo)

Solo el autor (ajena → 404). Campos opcionales `rating`, `comment`, `image_urls` (lista completa que reemplaza las actuales). Si la reseña está `HIDDEN` → 403 "Esta reseña fue ocultada por moderación y no puede editarse." Si el comentario está `BLOCKED`, el texto nuevo se guarda pero sigue bloqueado y la reseña queda `flagged_for_review=True` (la respuesta lo indica para que el frontend avise "Un administrador revisará tu nuevo comentario antes de publicarlo"). Fija `edited_at`, recalcula agregados si cambió `rating`.

#### `DELETE /reviews/{review_id}` (nuevo)

Solo el autor. Borrado físico (es su contenido), recalcula agregados, `204`.

#### Rutas legadas

- `POST /reviews/{review_id}/images`: `deprecated=True`; aplicar las mismas validaciones de URL y máximo de imágenes.
- `POST /reviews/{review_id}/reply`: `deprecated=True`; delegar en `upsert_reply` (deja de dar 500 al responder dos veces).

### 7.3 Reportes de contenido (B5)

#### `POST /reports` (nuevo)

```json
{ "target_type": "REVIEW", "target_id": 15, "reason": "OFFENSIVE", "details": "Insulta al personal" }
```

Cualquier usuario autenticado y `ACTIVE` (incluye restaurantes, que pueden reportar reseñas falsas sobre su local). Valida que el destino exista y sea visible para quien reporta. Ya reportado por el mismo usuario → 409. Límite `REPORTS_PER_DAY_LIMIT` → 429. No se puede reportar contenido propio → 400.
Al crear el **primer** reporte abierto de un destino, `notify_admins(ADMIN_REPORT_OPENED, link="/admin/reports")`.
Opcional: si `REPORT_AUTO_HIDE_THRESHOLD > 0` y una reseña alcanza ese número de reportes abiertos, se oculta automáticamente con `moderation_reason="Oculta automáticamente por reportes; pendiente de revisión."` y se registra en la bitácora con `admin_id=None`.

### 7.4 Panel del establecimiento: reseñas, respuestas y horarios (B4)

Todas usan `require_approved_restaurant` y resuelven el establecimiento por `owner_id`.

#### `GET /restaurant/reviews`

Parámetros: `status` (`all` \| `unanswered` \| `answered`), `rating`, `sort` (`recent` \| `rating_asc`), `skip`, `limit`. Respuesta `Page[ReviewPublic]` solo con reseñas `VISIBLE`.

#### `GET /restaurant/reviews/summary`

```json
{ "rating_avg": 4.3, "rating_count": 27, "ranking_score": 4.17, "category_rank": 2,
  "distribution": {"1": 1, "2": 1, "3": 3, "4": 9, "5": 13},
  "unanswered_count": 4, "response_rate": 0.85 }
```

#### `PUT /restaurant/reviews/{review_id}/reply`

`{"comment": "¡Gracias por visitarnos!"}` (1..1000 caracteres). Crea o actualiza (idempotente). Reseña de otro local o no visible → 404. Si la respuesta existente está bloqueada por moderación, el texto nuevo se guarda pero sigue bloqueada y queda `flagged_for_review=True`. El panel del establecimiento nunca recibe el texto original de un **comentario** bloqueado (ve el aviso), pero sí puede responder a la calificación. Notifica al autor (`REVIEW_REPLIED`, `link="/establishments/{id}#review-{review_id}"`) **solo al crearla**, no en cada edición.

#### `DELETE /restaurant/reviews/{review_id}/reply`

`204`; 404 si no hay respuesta.

#### `GET /restaurant/schedules` y `PUT /restaurant/schedules`

`PUT` reemplaza todos los horarios:

```json
[{"day_of_week": 0, "opening_time": "08:00", "closing_time": "15:00"},
 {"day_of_week": 0, "opening_time": "18:00", "closing_time": "02:00"}]
```

Reglas: `day_of_week` 0..6 (0 = lunes, como el resto del sistema); `opening_time != closing_time`; si `closing_time < opening_time` el tramo **cruza la medianoche**; sin solapes dentro del mismo día; máximo 3 tramos por día.

### 7.5 Administración (B5)

Todas con `require_admin`. Cada acción que cambia estado llama a `record_moderation_action(...)` y, si hay un afectado, a `notify(...)`.

#### Usuarios

| Método y ruta | Descripción |
|---|---|
| `GET /admin/users` | **Cambia a `Page[AdminUserListItem]`** (el frontend aún no lo usa). Filtros `search` (nombre, apodo, email, teléfono), `role`, `status`, `skip`, `limit`. Incluye `reviews_count` y `open_reports_count`. |
| `GET /admin/users/{id}` | Perfil, conteos, establecimientos que posee, últimas 10 reseñas, reportes recibidos y últimas acciones de moderación sobre él. |
| `PATCH /admin/users/{id}/role` | Existente. Añadir: no puede cambiarse el rol propio (400); no se cambia el rol de una cuenta `restaurant` (400, su rol va ligado al establecimiento); no se puede quitar el rol al último admin activo (400). Registrar `CHANGE_ROLE`. |
| `POST /admin/users/{id}/suspend` | `{"reason": "…"}` (5..1000). `status=SUSPENDED`. No a sí mismo ni al último admin. Notifica `ACCOUNT_SUSPENDED`. Si el usuario es `restaurant`, la respuesta incluye `establishment_id` para que la UI ofrezca suspender también el local. |
| `POST /admin/users/{id}/reactivate` | `ACTIVE` si `phone_verified` (o rol `restaurant`); si no, `PENDING_PHONE`. Notifica. |
| `POST /admin/users/{id}/notify` | `{"title": "…", "body": "…", "link": null}`. Aviso manual (`ADMIN_MESSAGE`). |

**Cuentas suspendidas:** `get_current_user` responde **403** `{"detail": "Tu cuenta está suspendida.", "code": "ACCOUNT_SUSPENDED", "reason": "…"}` para usuarios `SUSPENDED` (salvo en `POST /auth/logout`). `POST /auth/login` responde lo mismo. Así una cookie ya emitida deja de servir de inmediato.

#### Establecimientos

| Método y ruta | Descripción |
|---|---|
| `GET /admin/establishments` | Existente. Añadir filtro `status=SUSPENDED` y campos `rating_avg`, `rating_count`, `has_location`, `open_reports_count`, `establishment_type`. |
| `POST /admin/establishments/{id}/approve` | Existente. Notifica `ESTABLISHMENT_APPROVED` al dueño; devuelve `warnings` si no hay ubicación. |
| `POST /admin/establishments/{id}/reject` | Existente. **Solo desde `PENDING`** (antes también desde `APPROVED`). Notifica `ESTABLISHMENT_REJECTED`. Actualizar `test_incompatible_transitions_return_conflict`, que hoy prueba `APPROVED → REJECTED` como suspensión. |
| `POST /admin/establishments/{id}/suspend` | `{"reason"}`. `APPROVED → SUSPENDED`. Notifica al dueño y, con `PLAN_AFFECTED`, a los usuarios con planes futuros `SCHEDULED` en ese local. |
| `POST /admin/establishments/{id}/reactivate` | `SUSPENDED → APPROVED`. Notifica. |
| `PATCH /admin/establishments/{id}` | **Editar como el establecimiento**: `RestaurantProfileUpdate` + `establishment_type` + `reason` opcional. Registra `EDIT_ESTABLISHMENT` con valores antes/después y notifica `ESTABLISHMENT_EDITED_BY_ADMIN`. |
| `GET/POST /admin/establishments/{id}/products`, `PATCH/DELETE …/products/{product_id}` | Igual que `/restaurant/products`, sobre el local indicado. |
| `POST /admin/establishments/{id}/combos`, `PATCH/DELETE …/combos/{combo_id}` | Igual que `/restaurant/combos`. |
| `GET/POST /admin/establishments/{id}/images`, `DELETE …/images/{image_id}` | Igual que `/restaurant/images`. |
| `GET/PUT /admin/establishments/{id}/schedules` | Igual que `/restaurant/schedules`. |

**Cómo reutilizar sin duplicar:** crear `app/api/routes/catalog_router.py` con `build_catalog_router(establishment_dependency, *, audit: bool) -> APIRouter`, que define productos, combos, imágenes y horarios llamando a `restaurant_service`/`schedule_service`. `restaurant.py` lo monta con una dependencia que devuelve el `Establishment` de `require_approved_restaurant`; el router de admin lo monta con `get_establishment_for_admin(establishment_id)` y `audit=True` (registra `EDIT_CATALOG` y notifica al dueño). Las pruebas actuales de catálogo protegen esta refactorización.

> El admin **no** responde reseñas en nombre del establecimiento (la respuesta es la voz del local); sí puede ocultar respuestas.

#### Moderación de contenido

| Método y ruta | Descripción |
|---|---|
| `GET /admin/reviews` | `Page[AdminReviewItem]` con filtros `status` (`VISIBLE`/`HIDDEN`/`ALL`), `comment_status` (`VISIBLE`/`BLOCKED`), `flagged_for_review` (editadas tras un bloqueo), `establishment_id`, `user_id`, `rating`, `has_reports`, `search` (texto del comentario), orden por más reportadas o recientes. Incluye **siempre el texto original**, autor (con email), establecimiento, respuesta y `open_reports_count`. |
| `POST /admin/reviews/{id}/block-comment` | `{"category": "OFFENSIVE_LANGUAGE", "note": "Contiene insultos al personal.", "remove_images": false}`. `comment_status=BLOCKED`, `flagged_for_review=False`; con `remove_images=true` borra también sus imágenes. **No** recalcula agregados (las estrellas siguen contando). Notifica al autor `CONTENT_MODERATED` ("Tu comentario en {local} fue bloqueado: {categoría}.") con enlace a las normas de la comunidad. Bitácora `BLOCK_COMMENT` con copia del texto. |
| `POST /admin/reviews/{id}/unblock-comment` | `{"note"}` opcional. → `VISIBLE` y `flagged_for_review=False`. Sirve también para aprobar un comentario reescrito. Notifica `CONTENT_RESTORED`. |
| `POST /admin/reviews/{id}/hide` | `{"category", "reason"}` → `HIDDEN` (reseña completa), recalcula agregados, notifica al autor `CONTENT_MODERATED`. Para spam o reseñas falsas. |
| `POST /admin/reviews/{id}/restore` | → `VISIBLE`, recalcula, notifica `CONTENT_RESTORED`. |
| `DELETE /admin/reviews/{id}?reason=…` | Borrado físico para contenido ilegal. Guarda un snapshot (texto, rating, imágenes, autor) en `details` de la bitácora. Recalcula y notifica. |
| `POST /admin/review-replies/{id}/block` / `…/unblock` | Bloquea o desbloquea el texto de la respuesta del establecimiento (`BLOCKED_REPLY_NOTICE`), con `category` y `note`; notifica al dueño. |
| `DELETE /admin/review-images/{id}?reason=…` | Borra una imagen de reseña; notifica al autor. |

**Cuándo usar cada acción** (también va en la ayuda de la consola admin):

| Situación | Acción |
|---|---|
| Insultos, groserías, datos personales de terceros, enlaces o publicidad dentro de una opinión real | **Bloquear comentario** |
| Solo una foto es inapropiada | **Borrar imagen** |
| Reseña falsa, spam, cuenta que reseña sin haber ido, reseña duplicada con otra cuenta | **Ocultar reseña** |
| Contenido ilegal que no debe quedar ni en la base de datos | **Eliminar reseña** |
| Reincidencia | Además, **suspender** al autor |

#### Reportes

| Método y ruta | Descripción |
|---|---|
| `GET /admin/reports` | `Page[AdminReportItem]`, filtros `status` (por defecto `OPEN`), `target_type`, `reason`. Agrupa la vista previa del destino (`preview`: texto, URL de imagen o nombre) y `reports_on_target`. |
| `POST /admin/reports/{id}/resolve` | `{"action": "NONE" \| "BLOCK_COMMENT" \| "HIDE_CONTENT" \| "DELETE_CONTENT" \| "SUSPEND_OWNER", "category": "…", "note": "…"}` (`category` obligatoria salvo con `NONE`). Aplica la acción según el tipo de destino (ver tabla), resuelve **todos** los reportes abiertos del mismo destino, notifica a quienes reportaron (`REPORT_RESOLVED`) y al dueño del contenido. |
| `POST /admin/reports/{id}/dismiss` | `{"note"}`. Descarta todos los abiertos del mismo destino. |

| Destino | `BLOCK_COMMENT` | `HIDE_CONTENT` | `DELETE_CONTENT` | `SUSPEND_OWNER` |
|---|---|---|---|---|
| `REVIEW` | bloquear comentario | ocultar reseña | borrar reseña | suspender autor |
| `REVIEW_REPLY` | bloquear respuesta | bloquear respuesta | borrar respuesta | suspender establecimiento |
| `REVIEW_IMAGE` | — (400) | borrar imagen | borrar imagen | suspender autor |
| `ESTABLISHMENT` | — (400) | suspender establecimiento | — (400) | suspender cuenta dueña |
| `ESTABLISHMENT_IMAGE` | — (400) | borrar imagen | borrar imagen | suspender establecimiento |
| `MENU_ITEM` | — (400) | `is_available=False` | borrar ítem (409 si está en combos) | suspender establecimiento |
| `USER` | — (400) | suspender usuario | — (400) | suspender usuario |

#### Bitácora y panel

- `GET /admin/moderation-actions?admin_id&target_type&target_id&skip&limit` → `Page[ModerationActionItem]`.
- `GET /admin/dashboard` (ampliar sin romper): se conservan `users_count`, `establishments_count`, `reviews_count`; se añaden `pending_establishments`, `suspended_establishments`, `suspended_users`, `open_reports`, `hidden_reviews`, `reviews_last_7_days`, `scheduled_plans`, `establishments_without_location`.

### 7.6 Notificaciones (B1)

Usan `get_current_user` (cualquier rol y estado, salvo `SUSPENDED`), porque un restaurante `PENDING` debe poder ver que fue aprobado.

| Método y ruta | Descripción |
|---|---|
| `GET /notifications?unread_only=false&skip=0&limit=20` | `Page[NotificationResponse]`, más recientes primero. |
| `GET /notifications/unread-count` | `{"count": 3}`. Consulta barata para el polling. |
| `POST /notifications/{id}/read` | `204`. Ajena → 404. |
| `POST /notifications/read-all` | `204`. |
| `DELETE /notifications/{id}` | `204` (opcional). |

Servicio `app/services/notification_service.py`:

```python
async def notify(session, user_id, type_, title, body, *, link=None, data=None, dedupe_key=None) -> Notification | None:
    """Agrega la notificación a la sesión SIN hacer commit. Con dedupe_key existente devuelve None."""

async def notify_admins(session, type_, title, body, *, link=None, data=None) -> None: ...
```

Retención: el ciclo de B6 borra notificaciones leídas con más de `NOTIFICATIONS_RETENTION_DAYS` (90).

### 7.7 Planes (B6)

Solo rol `user` `ACTIVE` (dependencia `require_planner`). Todo filtrado por `user_id`.

#### `POST /plans`

```json
{
  "establishment_id": 3,
  "scheduled_at": "2026-11-20T19:30:00-05:00",
  "party_size": 4,
  "title": "Cumpleaños de Ana",
  "notes": "Mesa en terraza si es posible",
  "reminder_minutes_before": 120,
  "items": [ {"menu_item_id": 10, "quantity": 2, "notes": "sin cebolla"}, {"menu_item_id": 14, "quantity": 1} ]
}
```

| Regla | Error |
|---|---|
| `scheduled_at` con zona horaria (sin offset → 422); se guarda en UTC | 422 |
| `scheduled_at ≥ ahora + PLAN_MIN_LEAD_MINUTES` (15) y `≤ ahora + PLAN_MAX_DAYS_AHEAD` (365 días) | 400 |
| Establecimiento `APPROVED` | 404 |
| Si el local tiene horarios, la hora local (America/Bogota) debe caer dentro de un tramo (con soporte de medianoche) | 400 "El establecimiento está cerrado en ese horario." |
| `party_size` 1..50; `items` 0..30; `quantity` 1..99; ítems repetidos se fusionan sumando cantidades | 422 |
| Cada `menu_item_id` pertenece al establecimiento y está `is_available` | 400 con los ids inválidos |
| `reminder_minutes_before` ∈ `{15, 30, 60, 120, 1440}` o `null` | 422 |
| `reminder_at` (= `scheduled_at - minutos`) ya pasó | 400 "El recordatorio quedaría en el pasado; elige uno más corto." |
| Más de `PLAN_MAX_ACTIVE` (50) planes `SCHEDULED` futuros | 429 |

`total_amount = Σ unit_price × quantity` con el precio **actual** del catálogo, calculado en el servidor (nunca se acepta un total del cliente). Respuesta `201` con `PlanDetail`.

Validación de horario (`schedule_service.is_open_at`):

```python
def is_open_at(schedules: list[Schedule], local_dt: datetime) -> bool:
    minute = local_dt.hour * 60 + local_dt.minute
    today, yesterday = local_dt.weekday(), (local_dt.weekday() - 1) % 7   # weekday(): 0 = lunes
    for s in schedules:
        start, end = to_minutes(s.opening_time), to_minutes(s.closing_time)
        if start < end and s.day_of_week == today and start <= minute < end:
            return True
        if start > end:  # cruza medianoche
            if s.day_of_week == today and minute >= start:
                return True
            if s.day_of_week == yesterday and minute < end:
                return True
    return False
```

#### `GET /plans`

Parámetros: `from`, `to` (ISO con zona; rango máximo 92 días), `status`, `skip`, `limit`. Sin `from`/`to` devuelve los próximos (`scheduled_at ≥ ahora`) en orden ascendente. Respuesta `Page[PlanListItem]` (sin ítems; con `establishment: {id, name, address, latitude, longitude, profile_image_url}`, `items_count`, `total_amount`).

#### `GET /plans/{id}`

`PlanDetail`: plan + ítems + establecimiento + banderas calculadas:
- `establishment_available`: `false` si el local ya no está `APPROVED`.
- `items[].current_price` y `items[].price_changed` (precio actual distinto del congelado o producto eliminado/no disponible).
- `outside_schedule`: si con los horarios actuales ya no está abierto a esa hora.

#### `PATCH /plans/{id}`

Solo planes `SCHEDULED` y futuros. Cualquier campo de creación salvo `establishment_id`. Si llega `items`, reemplaza la lista y **recalcula el total con precios actuales**. Si cambian `scheduled_at` o `reminder_minutes_before`, recalcula `reminder_at` y pone `reminder_sent_at = None`.

#### `POST /plans/{id}/cancel` y `DELETE /plans/{id}`

Cancelar deja el plan en el historial (`CANCELLED`); eliminar lo borra. Ambos solo del dueño.

#### `GET /plans/{id}/calendar.ics` (confirmado)

Archivo para añadir el plan al calendario del celular o del computador (Apple Calendar en iPhone, Outlook, Samsung Calendar y otras). Solo el dueño del plan (ajeno → 404).

- Cabeceras: `Content-Type: text/calendar; charset=utf-8` y `Content-Disposition: attachment; filename="plan-{id}.ics"`.
- Se genera como texto en `app/services/calendar_service.py` (sin dependencias), siguiendo RFC 5545: fin de línea `CRLF`, líneas plegadas a 75 octetos y escape de `\`, `;`, `,` y saltos de línea.
- Contenido:
  ```
  BEGIN:VCALENDAR
  VERSION:2.0
  PRODID:-//PlanATi//Planes//ES
  CALSCALE:GREGORIAN
  METHOD:PUBLISH
  BEGIN:VEVENT
  UID:plan-{id}@planati
  DTSTAMP:{ahora UTC}Z
  DTSTART:{scheduled_at UTC}Z
  DTEND:{scheduled_at + PLAN_DEFAULT_DURATION_MINUTES UTC}Z
  SUMMARY:{título}
  LOCATION:{nombre del local}, {dirección}
  GEO:{lat};{lng}
  DESCRIPTION:{personas, platos con cantidades, total en COP y enlace al plan}
  URL:{FRONTEND_URL}/plans/{id}
  STATUS:CONFIRMED | CANCELLED
  BEGIN:VALARM                      (solo si hay recordatorio)
  ACTION:DISPLAY
  DESCRIPTION:{título}
  TRIGGER:-PT{reminder_minutes_before}M
  END:VALARM
  END:VEVENT
  END:VCALENDAR
  ```
- La `VALARM` hace que el propio calendario del teléfono también avise, además de la notificación dentro de PlanATi.
- El `UID` es estable: si el usuario descarga de nuevo el archivo tras editar el plan, el calendario lo actualiza en lugar de duplicarlo (en las apps que lo soportan).
- El enlace de **Google Calendar** no necesita backend: lo arma el frontend con la plantilla `calendar.google.com/calendar/render?action=TEMPLATE…`. En Android es la opción recomendada, porque la app de Google Calendar no importa archivos `.ics` descargados.

#### Recordatorios y cierre de planes — `app/services/reminder_service.py`

```python
async def dispatch_due_reminders(session: AsyncSession, now: datetime) -> int:
    """Idempotente. Seguro con varios workers."""
    # SELECT planes SCHEDULED con reminder_at <= now y reminder_sent_at IS NULL
    #   .with_for_update(skip_locked=True)   # PostgreSQL; SQLite lo ignora
    # Para cada plan:
    #   si scheduled_at <= now: marcar reminder_sent_at = now sin notificar (llegó tarde)
    #   si no: notify(PLAN_REMINDER, "Tu plan en {local} es {hoy|mañana} a las {hh:mm}",
    #                 link=f"/plans/{id}", dedupe_key=f"plan-reminder:{id}:{reminder_at.isoformat()}")
    #          reminder_sent_at = now
    # commit; devuelve cuántos envió

async def complete_past_plans(session: AsyncSession, now: datetime) -> int:
    # SCHEDULED con scheduled_at + PLAN_COMPLETE_AFTER_HOURS (3) < now -> COMPLETED
    # Si el usuario aún no reseñó ese local y puede hacerlo:
    #   notify(REVIEW_PROMPT, "¿Cómo te fue en {local}? Cuéntale a otros con tu reseña.",
    #          link=f"/establishments/{establishment_id}?review=1#reviews",   # el frontend abre el formulario
    #          dedupe_key=f"plan-review-prompt:{plan.id}")

async def purge_old_notifications(session: AsyncSession, now: datetime) -> int: ...
```

Ejecución — `app/workers/reminders.py`:

```python
async def reminders_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            async with session_factory() as session:
                now = utcnow()
                await dispatch_due_reminders(session, now)
                await complete_past_plans(session, now)
                await purge_old_notifications(session, now)
        except Exception:
            logger.exception("Fallo en el ciclo de recordatorios")
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=settings.reminder_poll_seconds)
```

- En `app/main.py`, añadir un `lifespan` que arranca la tarea si `settings.reminders_enabled` y la detiene al apagar.
- Pruebas: el `TestClient` del proyecto se crea sin `with`, así que no ejecuta el `lifespan`; aun así, poner `os.environ.setdefault("REMINDERS_ENABLED", "false")` al inicio de `tests/conftest.py`, antes de importar `app`. Las pruebas llaman a `dispatch_due_reminders(session, now=…)` directamente con un `now` fijo.
- Producción con varios workers de Uvicorn: es seguro por la idempotencia (`dedupe_key` único + `skip_locked`). Si se prefiere un solo ejecutor, poner `REMINDERS_ENABLED=false` y programar `python -m scripts.run_reminders` (con `--once`) cada minuto en cron o en el programador de tareas.

### 7.8 Favoritos (B7)

| Método y ruta | Descripción |
|---|---|
| `GET /favorites?skip&limit` | `Page[EstablishmentListItem]` de favoritos aprobados. |
| `GET /favorites/ids` | `{"establishment_ids": [...]}` de favoritos aprobados (para marcar tarjetas). |
| `PUT /favorites/{establishment_id}` | Idempotente, `204`. Solo establecimientos `APPROVED`. |
| `DELETE /favorites/{establishment_id}` | `204`. |

### 7.9 Privacidad y datos personales (B8)

> Base legal: Ley 1581 de 2012 y Decreto 1377 de 2013 (compilado en el Decreto 1074 de 2015). Este plan cubre el soporte técnico; **los textos legales debe revisarlos la universidad o un asesor** antes de publicar la app.

#### Versiones y aceptación

| Método y ruta | Descripción |
|---|---|
| `GET /legal/versions` | Público. `{"privacy_policy": "2026-11-01", "terms": "2026-11-01"}` desde la configuración. |
| `GET /users/me/consents` | Historial de aceptaciones del usuario. |
| `POST /users/me/consents` | `{"privacy_policy_version": "…", "terms_version": "…"}`. Deben ser las vigentes (si no, 409 con las vigentes). Inserta filas en `consents` con canal, IP y user agent, y actualiza las columnas de `users`. |

- **Registro:** `POST /auth/register` y `POST /auth/restaurant/register` exigen `accept_privacy_policy: true`, `accept_terms: true`, `privacy_policy_version` y `terms_version`. **Sin edad mínima ni casilla de mayoría de edad [DECISIÓN D10, 2026-11-13]**: el titular solo declara aceptar la política de tratamiento de datos y los términos. Si falta alguno → 422; versión desactualizada → 409 `CONSENT_VERSION_OUTDATED` con `current_versions`. El consentimiento se guarda en la misma transacción que la cuenta.
- **Google:** la cuenta se crea en el callback, antes de que el usuario vea las casillas; por eso `/complete-profile` debe llamar a `POST /users/me/consents` (canal `GOOGLE_COMPLETE_PROFILE`) antes de terminar.
- `UserResponse` añade `pending_consents: list[Literal["PRIVACY_POLICY", "TERMS"]]`, calculado comparando las columnas del usuario con las versiones vigentes.
- **Obligatoriedad:** `require_active_user`, `require_admin` y `require_restaurant_user` responden 403 `{"detail": "Debes aceptar la versión vigente de la política de datos y de los términos.", "code": "CONSENT_REQUIRED"}` si hay pendientes. `get_current_user` no lo exige, para que sigan funcionando `/users/me`, aceptar, descargar datos, eliminar la cuenta y cerrar sesión.
- Al publicar una versión nueva basta con cambiar `PRIVACY_POLICY_VERSION`/`TERMS_VERSION`: todos verán el aviso de nueva aceptación en su siguiente visita.

#### Derechos del titular

| Método y ruta | Descripción |
|---|---|
| `GET /users/me/export` | JSON descargable (`Content-Disposition: attachment; filename="mis-datos-planati.json"`) con perfil, reseñas (incluido el texto original de las bloqueadas), planes con ítems, favoritos, consentimientos y notificaciones de los últimos 90 días. Máximo uno cada `DATA_EXPORT_COOLDOWN_MINUTES` (429). |
| `POST /users/me/delete/send-code` | Envía un código SMS al teléfono verificado para confirmar la eliminación (reutiliza el proveedor SMS y los límites del OTP). Necesario para cuentas de Google, que no conocen su contraseña. |
| `DELETE /users/me` | `{"confirmation": "ELIMINAR", "password": "…"}` o `{"confirmation": "ELIMINAR", "code": "123456"}`. Solo rol `user`; `restaurant` y `admin` reciben 409 "Solicita la eliminación de tu cuenta a soporte". |

Efectos de `DELETE /users/me` (una sola transacción) **[DECISIÓN D9, ajustada 2026-11-13: borrar el contenido sin romper la trazabilidad]**:

- **Se borra** (borrado físico): reseñas con sus imágenes y las respuestas del local, recalculando los agregados de los locales afectados; planes con sus ítems; favoritos; notificaciones; códigos OTP y de Google.
- **La fila de `users` no se borra: queda como lápida anonimizada** (`status=DELETED`, `deleted_at`, nombre "Usuario eliminado", correo `eliminado-{id}@eliminado.planati.invalid`, sin apodo, foto, teléfono, `google_sub` ni contraseña utilizable). El correo y el teléfono quedan libres para registrarse de nuevo. Así la bitácora, los reportes y los consentimientos siguen apuntando a un id válido sin guardar datos personales. La sesión deja de valer (401) y el admin no ve la lápida salvo con `status=DELETED`, ni puede suspenderla, cambiarle el rol ni avisarle (409).
- **Consentimientos:** se conservan (documento, versión, canal y fecha) como prueba de la autorización, sin IP ni user agent.
- **Bitácora de moderación:** las entradas sobre sus reseñas, sus fotos o su cuenta conservan acción, ids, categoría y estados, pero `details` pierde el texto, las fotos y los mensajes (`"redacted": "ACCOUNT_DELETED"`). Se añade una entrada automática `DELETE_ACCOUNT` (`admin_id=None`) con los conteos.
- **Reportes:** los abiertos sobre su contenido o su cuenta se cierran (`RESOLVED`, "Contenido eliminado: su autor eliminó la cuenta."). Los que **hizo** se conservan (siguen en la cola del admin si estaban abiertos) apuntando a la lápida, y ya no generan avisos.
- Se limpia la cookie de sesión. Los objetos de R2 se borran en segundo plano o en B10.
- Una cuenta suspendida no puede autoeliminarse (`get_current_user` la rechaza con 403), así no evade una sanción.

#### Solicitudes de los titulares (opcional dentro de B8)

`POST /privacy/requests` (consulta, actualización, rectificación, supresión, revocatoria o reclamo; también sin sesión, con `contact_email`) calcula `due_at` en días hábiles (saltando fines de semana y festivos de Colombia con el paquete `holidays`) y notifica a los admins. Cola del admin: `GET /admin/privacy/requests` y `POST /admin/privacy/requests/{id}/resolve`. Si no se implementa, la política debe indicar un correo de contacto para estas solicitudes.

#### Minimización

- Las coordenadas del usuario en `/nearby` y `/map` no se guardan ni se registran en logs.
- La IP y el user agent solo se guardan en `consents`, como prueba de la autorización.
- El autor público de una reseña es solo `display_name` y `picture`.

---

## 8. Puntuación y posicionamiento (`app/services/rating_service.py`)

### 8.1 Agregados

```python
async def recalculate_establishment_rating(session: AsyncSession, establishment_id: int) -> None:
    count, total = (await session.execute(
        select(func.count(Review.id), func.coalesce(func.sum(Review.rating), 0))
        .where(Review.establishment_id == establishment_id, Review.status == "VISIBLE")
    )).one()
    establishment = await session.get(Establishment, establishment_id)
    establishment.rating_count = count
    establishment.rating_sum = total
    establishment.rating_avg = round(total / count, 2) if count else None
    establishment.ranking_score = bayesian_score(total, count)
```

Se llama tras crear, editar (si cambió el rating), borrar, ocultar o restaurar una reseña, **sin commit**.

### 8.2 Puntuación bayesiana (ranking)

```
ranking_score = (rating_sum + m · C) / (rating_count + m)
```

- `m = RANKING_MIN_REVIEWS` (5): cuántas reseñas "pesa" el valor previo.
- `C = RANKING_PRIOR_MEAN` (3.5): puntuación supuesta de un local sin reseñas.

| Local | Reseñas | Promedio | `ranking_score` |
|---|---|---|---|
| A | 1 | 5,0 | (5 + 17,5) / 6 = **3,75** |
| B | 40 | 4,6 | (184 + 17,5) / 45 = **4,48** |
| C | 0 | — | 17,5 / 5 = **3,50** |
| D | 12 | 2,5 | (30 + 17,5) / 17 = **2,79** |

B queda por encima de A aunque A tenga promedio perfecto con una sola reseña, y un local nuevo (C) no queda enterrado bajo uno mal calificado (D). Cuando haya volumen suficiente, `C` puede pasar a ser el promedio global y recalcularse con `scripts/recompute_ratings.py`.

### 8.3 Ordenamientos

| `sort` | Criterio |
|---|---|
| `ranking` | `ranking_score DESC, rating_count DESC, name` (por defecto en el directorio) |
| `rating` | `rating_avg DESC NULLS LAST, rating_count DESC` |
| `reviews` | `rating_count DESC` |
| `recent` | `created_at DESC` |
| `distance` | `distance_km ASC` (solo `/nearby`) |
| `relevance` | (solo `/nearby`) `w · (ranking_score − 1) / 4 + (1 − w) · (1 − min(distance_km / radius_km, 1))`, con `w = RELEVANCE_RATING_WEIGHT` (0,6) |

`rating_distribution`: `SELECT rating, COUNT(*) … WHERE status = 'VISIBLE' GROUP BY rating`, completando con ceros del 1 al 5.

---

## 9. Seguridad y reglas transversales

- **Visibilidad pública:** solo establecimientos `APPROVED`; solo reseñas y respuestas `VISIBLE`.
- **Privacidad:** el autor público de una reseña es solo `display_name` + `picture`; nunca email, teléfono ni nombre completo. Los planes son privados. Las coordenadas del usuario en `/nearby` y `/map` no se guardan ni se registran en logs.
- **Imágenes de reseñas:** solo URLs bajo `{R2_PUBLIC_BASE_URL}/reviews/`, máximo 5, sin duplicados. Las imágenes huérfanas en R2 (subidas y no usadas) se limpian en B10.
- **Antiabuso:** límites diarios de reseñas y reportes (consultas `COUNT` por `created_at ≥ inicio del día local`), máximo de planes activos, unicidad de reseña y de reporte.
- **Protecciones del admin:** no auto-degradarse ni auto-suspenderse; nunca dejar el sistema sin un admin activo.
- **Suspensión:** se comprueba en `get_current_user` (cubre todas las rutas, incluso `require_restaurant_user`). `EstablishmentAccessError.messages` añade `"SUSPENDED": "Establecimiento suspendido"`. `reapply` sigue permitido solo desde `REJECTED`.
- **Texto plano:** se guarda sin HTML; `strip()` y límites de longitud en todos los campos de texto.
- **Texto bloqueado:** solo `to_public_review`/`to_public_reply` convierten reseñas y respuestas a su forma pública; una prueba verifica que ninguna ruta pública ni del panel del establecimiento devuelve el texto de un comentario bloqueado.
- **Datos personales:** consentimiento versionado y obligatorio, exportación y eliminación de la cuenta (7.9).
- **Clave de Google Maps:** el backend no guarda ni expone ninguna clave de Google Maps; su protección se hace en Google Cloud y en el frontend (sección 3.1 del plan del frontend).
- **CSRF, cookie, clave secreta y copias de seguridad:** ver 9.1–9.5 (confirmado como revisión obligatoria antes de publicar).

### 9.1 Protección CSRF

Completa la sección 7 de `GUIA_AUTENTICACION_COOKIE_HTTPONLY.md` con dos capas. Se implementa en **B0**, porque cambia el cliente HTTP del frontend y las pruebas que usan todas las fases siguientes.

**Capa 1 — Verificación de origen** (todas las peticiones `POST`, `PUT`, `PATCH`, `DELETE`):

| Caso | Resultado |
|---|---|
| Trae `Authorization: Bearer …` | Exenta: el navegador no añade esa cabecera por su cuenta, así que no es atacable por CSRF. |
| Trae `Origin` | Debe estar en `CSRF_TRUSTED_ORIGINS` (por defecto `CORS_ORIGINS` + `FRONTEND_URL`); si no → 403. |
| Sin `Origin`, con `Referer` | Se compara el origen del `Referer`. |
| Sin ninguno de los dos | Se rechaza **solo si trae la cookie de sesión** (los navegadores actuales siempre envían `Origin` en estas peticiones; clientes como `curl` sin cookie siguen funcionando). |

Aplica también a `POST /auth/login`, `/auth/register`, `/auth/restaurant/register` y `/auth/google/exchange`, para evitar el "login CSRF" (que un sitio ajeno inicie sesión al usuario con una cuenta del atacante).

**Capa 2 — Token CSRF por sesión** (peticiones que cambian estado autenticadas por cookie):

- `issue_access_token` añade al JWT los claims `iat` y `csrf = secrets.token_urlsafe(32)`.
- `AuthResponse` (login, registro, registro de restaurante y canje de Google) devuelve `csrf_token` con ese valor. **No es el JWT** y por sí solo no sirve para autenticarse.
- `GET /auth/csrf` → `{"csrf_token": "…"}` leyendo el claim de la cookie; lo usa el frontend al recargar la página, porque guarda el token solo en memoria. Sin sesión → 401.
- En `POST`/`PUT`/`PATCH`/`DELETE` con cookie de sesión y sin Bearer, la cabecera `X-CSRF-Token` debe coincidir con el claim (`secrets.compare_digest`).
- Exentas del token (no de la capa 1): las rutas que crean la sesión (login, registros, canje de Google) y `POST /auth/logout`.
- El token cambia en cada inicio de sesión y caduca con el JWT. Va dentro del JWT y no en una segunda cookie, para que funcione aunque frontend y API estén en subdominios distintos y sin guardar estado en el servidor.

**Implementación:** una dependencia global `csrf_protect` en `app/core/csrf.py`, registrada con `FastAPI(dependencies=[Depends(csrf_protect)])`, con la lista de rutas exentas del token. Error común:

```json
{"detail": "La solicitud fue rechazada por seguridad. Recarga la página e inténtalo de nuevo.", "code": "CSRF_FAILED"}
```

(403). **Reglas complementarias:** ninguna ruta `GET` cambia estado (auditar; solo se aceptan el inicio y el callback de Google OAuth, protegidos por `state`). En producción, CORS con orígenes, métodos y cabeceras explícitos (`Content-Type`, `X-CSRF-Token`, `Authorization`).

**Pruebas (`tests/test_csrf.py`):** `Origin` ajeno → 403; sin token o con token incorrecto → 403; token correcto → 2xx; Bearer exento; `GET` no afectado; login desde un origen ajeno → 403; el token cambia tras volver a iniciar sesión; `GET /auth/csrf` con y sin sesión. Para no tocar cada prueba existente, `make_client()` en `conftest.py` envía por defecto `Origin: http://localhost:3000` y registra un `event_hook` de respuesta de httpx que copia `csrf_token` de las respuestas de autenticación a la cabecera `X-CSRF-Token` del cliente.

### 9.2 Cookie solo por HTTPS y topología de dominios

- **Atributos centralizados:** una función `session_cookie_params()` en `app/core/security.py`, usada por `set_auth_cookie`, `clear_auth_cookie` (borrar con los mismos atributos para que el navegador la elimine siempre) y la cookie `oauth_state`.
- **Producción (`APP_ENV=production`):** `Secure` siempre (se ignora `ACCESS_TOKEN_COOKIE_SECURE=false`), `HttpOnly`, `Path=/`, `SameSite=Lax`. `SameSite=None` solo se permite con `Secure` y solo si la topología lo exige; `Strict` no se usa, porque quien llega desde un enlace externo (p. ej. WhatsApp) aparecería sin sesión en la primera navegación.
- **Topología [DECISIÓN D12]:** se recomienda que **frontend y API compartan dominio** (`https://<dominio>` sirve la app y `https://<dominio>/api/v1` llega al backend mediante un *reverse proxy* o los `rewrites` de Next.js). Así la cookie es de primera parte, `proxy.ts` la ve y CSRF y CORS se simplifican. Alternativa: API en `api.<dominio>` con `ACCESS_TOKEN_COOKIE_DOMAIN=<dominio>` (setting nuevo) para que el frontend también reciba la cookie. Sin una de las dos, las rutas protegidas no funcionarán en producción (hallazgo 28).
- **HTTPS obligatorio:** redirección de HTTP a HTTPS y `Strict-Transport-Security: max-age=31536000; includeSubDomains` en el proxy (o con un middleware cuando `APP_ENV=production`). `FRONTEND_URL`, `CORS_ORIGINS` y `GOOGLE_REDIRECT_URI` deben ser `https://` en producción.
- Opcional, con la topología de mismo dominio: renombrar la cookie a `__Host-planati_session` (el prefijo obliga a `Secure`, `Path=/` y sin `Domain`); el nombre se lee de configuración en backend y en `proxy.ts`.
- **Pruebas (`tests/test_cookies.py`):** con `APP_ENV=production` la cookie de sesión y la de `oauth_state` salen con `Secure; HttpOnly; SameSite=lax`; el logout la borra con los mismos atributos.

### 9.3 Clave secreta fuerte

- Generarla con `python -c "import secrets; print(secrets.token_urlsafe(64))"`. Una distinta por entorno (desarrollo, pruebas en la nube, producción).
- Guardarla solo en las variables secretas del hosting y en el `.env` local; `.env.example` conserva un marcador de posición.
- **Validación al arrancar (9.5):** en producción se rechaza una clave por defecto (`development-secret`, `replace-with-a-local-secret`, `change-me`), de menos de 43 caracteres o formada por un solo carácter repetido.
- **Rotación:** cambiar la clave invalida todas las sesiones, los `state` de OAuth en curso y los tokens CSRF (todos vuelven a iniciar sesión). Hacerlo si se filtra o cuando sale del equipo alguien con acceso. Documentar el procedimiento en `docs/OPERACION.md`.
- Mismo criterio para los demás secretos: `GOOGLE_CLIENT_SECRET`; token de R2 con permiso solo de lectura y escritura de objetos sobre su bucket; contraseña fuerte de PostgreSQL (las credenciales `planati`/`planati` del Compose son solo para local y su puerto no se expone en el servidor); credenciales del proveedor SMS.

### 9.4 Copias de seguridad de la base de datos

#### 9.4.1 MVP local (se implementa ahora, en B0)

PostgreSQL corre en el Docker Compose del proyecto (contenedor `planati-postgres`, volumen `planati_postgres_data`). La base se pierde con `docker compose down -v`, al borrar el volumen o al reinstalar Docker, y algunas migraciones de este plan modifican datos (la `0010` elimina reseñas duplicadas). Por eso se implementa una copia **local** sencilla, en Python para que funcione igual en Windows:

```bash
python -m scripts.backup_db create [--tag pre-0010]   # nueva copia
python -m scripts.backup_db list                      # copias disponibles, con fecha y tamaño
python -m scripts.backup_db restore backups/planati-20261112-1830-pre-0010.dump [--target planati_restore]
python -m scripts.backup_db prune [--keep 10]         # borra las más antiguas sin etiqueta
```

- `create` ejecuta `docker exec planati-postgres pg_dump -U planati -Fc --no-owner planati` y guarda la salida en `backups/planati-AAAAMMDD-HHMM[-etiqueta].dump` (carpeta **fuera** del volumen de Docker). Si `docker` no está disponible y `pg_dump` sí, usa `DATABASE_URL`. Al terminar ejecuta `prune` automáticamente.
- `restore` restaura con `pg_restore --clean --if-exists --no-owner`. Sin `--target`, sobrescribe la base `planati` y **pide confirmación** escribiendo `RESTAURAR`; con `--target`, crea esa base y restaura ahí (sirve para revisar una copia sin tocar la actual). Al terminar muestra `alembic current` y el conteo de filas de `users`, `establishments` y `reviews`.
- `prune` conserva las `BACKUP_KEEP` (10) copias más recientes sin etiqueta y **todas** las etiquetadas. La función que decide qué borrar es pura y tiene prueba (`tests/test_backup_retention.py`).
- Errores claros y código de salida distinto de 0 si el contenedor no está corriendo o el volcado falla.
- `backups/` en `.gitignore` (las copias pueden contener datos personales de cuentas de prueba).

**Cuándo hacer copia en local:**

| Momento | Comando |
|---|---|
| Antes de aplicar migraciones nuevas (`alembic upgrade head`) | `create --tag pre-<revisión>` |
| Antes de `python -m scripts.seed_demo down` o de pruebas manuales destructivas | `create --tag pre-pruebas` |
| Antes de `docker compose down -v` o de reinstalar Docker | `create --tag pre-docker` |
| Si hay datos de prueba que costó crear | `create` semanal |

Recomendación: copiar de vez en cuando la carpeta `backups/` a una unidad en la nube personal o a otro disco, porque si falla el disco del computador se pierden la base y sus copias a la vez.

#### 9.4.2 Al publicar (pendiente, fase B9)

**[DECISIÓN D13]** Depende de dónde se aloje PostgreSQL en producción:

| Alojamiento | Qué hacer |
|---|---|
| PostgreSQL administrado (proveedor en la nube) | Activar las copias automáticas diarias y la recuperación a un punto en el tiempo si el plan la ofrece; **además**, un volcado lógico semanal fuera del proveedor. |
| Servidor propio / Docker | `scripts/backup_db.py create` diario (cron, temporizador de systemd o Programador de tareas de Windows). |

Ampliación de `scripts/backup_db.py` para producción:

1. Ejecuta `pg_dump --format=custom --no-owner` (por `DATABASE_URL`, o dentro del contenedor con `docker exec planati-postgres pg_dump -U planati -Fc planati`).
2. Nombra el archivo `planati-AAAAMMDD-HHMM[-etiqueta].dump` y lo **cifra** antes de subirlo (por ejemplo con `age` o GPG).
3. Lo sube a un bucket **privado y distinto** del de imágenes (p. ej. `planati-backups`), con credenciales propias de solo escritura.
4. Aplica la retención: 7 diarias, 4 semanales y 6 mensuales (configurable). La función que decide qué borrar es pura y tiene prueba unitaria.
5. Termina con código distinto de 0 y un log claro si algo falla. Una comprobación aparte alerta si no hay copia en las últimas 26 h.

**Antes de cada migración en producción:** `python -m scripts.backup_db --tag pre-<revisión>`.

**Restauración probada:** una vez al mes y antes de publicar, restaurar en una base temporal (`pg_restore --clean --if-exists -d planati_restore archivo.dump`), ejecutar `alembic current`, contar filas de las tablas principales y anotar la fecha de la prueba. Los pasos exactos van en `docs/OPERACION.md`.

**Privacidad:** las copias contienen datos personales. Van cifradas, solo 1 o 2 personas tienen acceso, y la política de datos (7.9) debe indicar cuánto tiempo se conservan (los datos de una cuenta eliminada desaparecen de las copias cuando estas vencen).

**Imágenes (opcional):** copia semanal del bucket de R2 a otro bucket con `rclone sync`.

### 9.5 Validación al arrancar y lista de verificación

`app/core/startup_checks.py::validate_settings(settings)` se llama en el `lifespan`. Con `APP_ENV=production` **impide arrancar** y lista todos los problemas si:

- `SECRET_KEY` es débil o un valor por defecto (9.3).
- La cookie no es `Secure`, o `SameSite=None` sin `Secure`.
- `FRONTEND_URL`, `CORS_ORIGINS` o `GOOGLE_REDIRECT_URI` no usan `https://`, contienen `localhost` o `*`.
- `SMS_PROVIDER=mock`.
- `DATABASE_URL` usa las credenciales `planati:planati`.
- Las variables de R2 conservan los marcadores de `.env.example`.

Además, en producción `/docs`, `/redoc` y `/openapi.json` quedan desactivados salvo `ENABLE_API_DOCS=true`. Pruebas en `tests/test_production_settings.py`, una por cada regla.

**Lista de verificación antes de publicar** (manual; se ejecuta en B9 y se guarda el resultado en `docs/OPERACION.md`):

- [ ] CSRF activo: una petición desde un origen ajeno o sin token es rechazada en el servidor publicado.
- [ ] La cookie de sesión aparece con `Secure`, `HttpOnly` y `SameSite=Lax` en las herramientas del navegador; `http://` redirige a `https://`; la cabecera HSTS está presente.
- [ ] Las rutas protegidas del frontend funcionan en el dominio real (`proxy.ts` ve la cookie).
- [ ] La aplicación no arranca con una configuración insegura (probar quitando `SECRET_KEY`).
- [ ] Hay una copia de seguridad de hoy y una restauración probada este mes.
- [ ] `/docs` no es público; `SMS_PROVIDER` es real; PostgreSQL no expone su puerto a internet.

---

## 10. Configuración

### 10.1 `app/core/config.py` y `.env.example`

```env
APP_TIMEZONE=America/Bogota
# sur,oeste,norte,este (Colombia continental + San Andrés). Vacío = sin restricción.
SERVICE_AREA_BOUNDS=-4.3,-81.8,13.6,-66.8
NEARBY_MAX_RADIUS_KM=50
MAP_MAX_MARKERS=500
RANKING_MIN_REVIEWS=5
RANKING_PRIOR_MEAN=3.5
RELEVANCE_RATING_WEIGHT=0.6
REVIEW_MAX_IMAGES=5
REVIEW_COMMENT_MAX_LENGTH=2000
REVIEWS_PER_DAY_LIMIT=10
REPORTS_PER_DAY_LIMIT=20
REPORT_AUTO_HIDE_THRESHOLD=0
REMINDERS_ENABLED=true
REMINDER_POLL_SECONDS=60
PLAN_MIN_LEAD_MINUTES=15
PLAN_MAX_DAYS_AHEAD=365
PLAN_MAX_ACTIVE=50
PLAN_COMPLETE_AFTER_HOURS=3
PLAN_DEFAULT_DURATION_MINUTES=120
NOTIFICATIONS_RETENTION_DAYS=90
PRIVACY_POLICY_VERSION=2026-11-01
TERMS_VERSION=2026-11-01
DATA_EXPORT_COOLDOWN_MINUTES=60

# Seguridad (9.1–9.5)
# Generar con: python -c "import secrets; print(secrets.token_urlsafe(64))"
SECRET_KEY=replace-with-a-local-secret
# Vacío = CORS_ORIGINS + FRONTEND_URL
CSRF_TRUSTED_ORIGINS=
# En producción se fuerza a true
ACCESS_TOKEN_COOKIE_SECURE=false
ACCESS_TOKEN_COOKIE_SAMESITE=lax
# Solo si la API va en otro subdominio (D12)
ACCESS_TOKEN_COOKIE_DOMAIN=
# En producción: false
ENABLE_API_DOCS=true
```

Añadir una propiedad `service_area` que convierta `SERVICE_AREA_BOUNDS` en una tupla o `None`, y una propiedad `csrf_trusted_origin_list`.

El script de copias lee sus propias variables (no forman parte de `Settings` de la API). MVP local: `BACKUP_DIR=backups`, `BACKUP_KEEP=10`, `BACKUP_DOCKER_CONTAINER=planati-postgres` (todas con esos valores por defecto). Al publicar se añaden `BACKUP_BUCKET`, `BACKUP_ACCESS_KEY_ID`, `BACKUP_SECRET_ACCESS_KEY`, `BACKUP_ENDPOINT_URL`, `BACKUP_ENCRYPTION_RECIPIENT` y `BACKUP_RETENTION` (`7d,4w,6m`).

**Clave secreta en local:** aunque la validación estricta solo bloquea en producción, el `.env` local debe usar también una clave generada con `secrets.token_urlsafe(64)` en lugar de `replace-with-a-local-secret`; cuesta un minuto y evita que alguien la copie a un entorno real.

**Zona horaria (confirmada):** `APP_TIMEZONE=America/Bogota` es la única fuente para convertir a hora local (validar horarios, textos de recordatorios, "inicio del día" de los límites diarios). Se guarda en UTC y se convierte con `app/core/time.py`. Una prueba verifica que un plan a las 19:30 hora de Colombia se guarda como 00:30 UTC del día siguiente y se valida contra el horario del día local correcto.

### 10.2 Dependencias

- `requirements.txt`: añadir `tzdata` (necesario para `zoneinfo` en Windows).
- Si se implementan las solicitudes de titulares (7.9): `holidays` (festivos de Colombia para los días hábiles).
- Opcionales para B10: `geoalchemy2` (PostGIS), `pywebpush` (Web Push), `slowapi` (límite de peticiones por IP).

### 10.3 Documentación

- `README.md`: quitar `GOOGLE_MAPS_API_KEY` del backend (va en el frontend como `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY`); actualizar la tabla de funcionalidades; documentar el ciclo de recordatorios y `scripts/recompute_ratings.py`.
- `CLAUDE.md`: añadir a "Planning docs" este archivo y una línea sobre notificaciones/recordatorios, la regla de UTC y la protección CSRF (las pruebas deben enviar `Origin` y `X-CSRF-Token`; `make_client()` ya lo hace).
- `GUIA_AUTENTICACION_COOKIE_HTTPONLY.md`: sustituir la sección 7 (CSRF pendiente) por el diseño implementado (9.1).
- `docs/OPERACION.md` (nuevo): despliegue con HTTPS y topología elegida, generación y rotación de secretos, copias de seguridad, restauración paso a paso y registro de pruebas, lista de verificación antes de publicar.
- `scripts/seed_demo.py`: ver 10.4.

### 10.4 Datos demo en Cúcuta (confirmado)

Actualizar `scripts/seed_demo.py` (conservar `up`, `status`, `down` y el dominio `@demo.planati.test`, que permite borrarlo todo sin tocar datos reales):

- **Centro:** `7.889100, -72.496700`. Cada local se desplaza al azar dentro de un radio de ~4 km (casco urbano). Las coordenadas son aproximadas y no tienen por qué coincidir con la dirección escrita; anotarlo en el docstring.
- **Direcciones** con barrios conocidos de la ciudad: Centro, Caobos, La Riviera, Quinta Oriental, Barrio Blanco, Prados del Este, Los Acacios, La Ceiba, Atalaya, San Luis, Guaimaral (p. ej. "Av. 0 # 11-50, Caobos, Cúcuta"). `city="Cúcuta"`.
- **Tipos y categorías variados:** restaurantes (comida típica nortesantandereana, parrilla, comida rápida), cafés, bares (con un horario que cruce la medianoche), hoteles y experiencias, con `location_source` mezclado.
- **Horarios** para todos los locales; uno sin horarios para probar ese caso.
- **Reseñas** con estrellas, unas sin texto, algunas con respuesta, **un comentario bloqueado** (con categoría) y una reseña oculta; recalcular los agregados al terminar (`recompute_ratings`).
- **Usuarios** con favoritos; **planes** pasados (`COMPLETED`), futuros con recordatorio y uno cancelado; algunas **notificaciones** y **reportes** abiertos.
- **Consentimientos** con las versiones vigentes para todas las cuentas demo, para que no les aparezca el aviso de aceptación.
- Un **admin demo** opcional (`admin@demo.planati.test`) solo si se pasa `--with-admin`, para no crear cuentas con privilegios por accidente.

---

## 11. Archivos

### 11.1 Nuevos

```
app/core/time.py, csrf.py, startup_checks.py
app/models/notification.py, report.py, moderation.py, plan.py, favorite.py, privacy.py
app/schemas/common.py (Page[T]), geo.py, notification.py, moderation.py, report.py, plan.py, favorite.py, privacy.py
app/services/notification_service.py, rating_service.py, moderation_service.py, report_service.py,
             plan_service.py, schedule_service.py, reminder_service.py, favorite_service.py,
             calendar_service.py, privacy_service.py
app/api/routes/notifications.py, plans.py, reports.py, favorites.py, legal.py, privacy.py,
               catalog_router.py, admin_users.py, admin_moderation.py
app/workers/__init__.py, reminders.py
scripts/recompute_ratings.py, run_reminders.py, backup_db.py
docs/OPERACION.md
migrations/versions/0008 … 0014
tests/test_notifications.py, test_geo_nearby_map.py, test_establishment_location.py,
      test_reviews_v2.py, test_rating_ranking.py, test_review_replies.py, test_schedules.py,
      test_admin_users.py, test_admin_moderation.py, test_admin_establishment_management.py,
      test_reports.py, test_plans.py, test_reminders.py, test_calendar_ics.py, test_favorites.py,
      test_comment_blocking.py, test_consents.py, test_account_deletion.py, test_timezone.py,
      test_csrf.py, test_cookies.py, test_production_settings.py, test_backup_retention.py
```

### 11.2 Modificados

`app/main.py` (routers nuevos, `lifespan` con `validate_settings`, dependencia global `csrf_protect`, `/docs` según `ENABLE_API_DOCS`, CORS explícito en producción), `app/core/security.py` (`session_cookie_params`, claims `iat` y `csrf`), `GUIA_AUTENTICACION_COOKIE_HTTPONLY.md`, `.gitignore` (`backups/`), `app/api/dependencies.py` (suspensión, `require_reviewer`, `require_planner`, `get_establishment_for_admin`), `app/core/config.py`, `app/models/__init__.py`, `app/models/establishment.py`, `app/models/review.py`, `app/models/user.py`, `app/schemas/establishment.py`, `app/schemas/review.py`, `app/schemas/restaurant.py`, `app/schemas/admin.py`, `app/schemas/user.py`, `app/services/establishment_service.py`, `app/services/review_service.py`, `app/services/restaurant_service.py`, `app/services/auth_service.py`, `app/services/storage.py`, `app/api/routes/establishments.py`, `app/api/routes/reviews.py`, `app/api/routes/restaurant.py`, `app/api/routes/admin.py`, `app/api/routes/auth.py`, `tests/conftest.py`, `tests/test_admin_approvals.py`, `scripts/seed_demo.py`, `README.md`, `CLAUDE.md`, `.env.example`, `requirements.txt`.

### 11.3 Fixtures nuevos en `tests/conftest.py`

- `user_client(suffix="a") -> (TestClient, user_id)`: crea un usuario `user` activo con teléfono verificado y devuelve un cliente con sesión.
- `approved_restaurant_at(suffix, latitude, longitude)`: como `approved_restaurant` pero con coordenadas concretas.
- `db_session()`: sesión asíncrona sobre la misma base temporal para llamar servicios directamente (envolver con `asyncio.run`).

---

## 12. Plan de tareas por fases

### Fase B0 — Base transversal

- [x] `tzdata` en requirements; settings nuevos de la sección 10.1 en `config.py` y `.env.example`.
- [x] `app/core/time.py` (`utcnow`, `ensure_utc`, `to_local`, `LOCAL_TZ`).
- [x] `app/schemas/common.py` con `Page[T]`.
- [x] Fixtures `user_client`, `approved_restaurant_at`, `db_session`; `REMINDERS_ENABLED=false` al inicio de `conftest.py`.
- [x] Seed movido a Cúcuta (centro, barrios, tipos y horarios; sección 10.4). Cada fase siguiente añade al seed sus propios datos demo (reseñas bloqueadas en B5, planes en B6, favoritos en B7, consentimientos en B8).
- [x] Prueba de zona horaria (`test_timezone.py`): conversión local ↔ UTC y "inicio del día" en America/Bogota.
- [x] **Seguridad base (se hace aquí para que todas las fases nazcan protegidas):** CSRF de dos capas (9.1) con `GET /auth/csrf` y `csrf_token` en `AuthResponse`; `session_cookie_params()` (9.2); `validate_settings` y `/docs` según configuración (9.5); `make_client()` con `Origin` y el `event_hook` del token; pruebas `test_csrf.py`, `test_cookies.py`, `test_production_settings.py`. **Se despliega junto con F0**, que añade el token a las peticiones del frontend.
- [x] **Copia de seguridad local (9.4.1):** `scripts/backup_db.py` con `create`, `list`, `restore`, `prune`; `backups/` en `.gitignore`; `tests/test_backup_retention.py`; sección "Copias de seguridad" en `README.md` y en `CLAUDE.md` (hacer `create --tag pre-<revisión>` antes de cada migración de este plan). Probar una restauración completa con `--target planati_restore`.
- [x] Generar una `SECRET_KEY` propia para el `.env` local (10.1). *(El `.env` local ya tenía una clave fuerte de 64 caracteres hexadecimales; no se cambió para no cerrar sesiones.)*
- **Hecho cuando:** `pytest` sigue en verde (incluidas las 38 pruebas actuales, sin editarlas una por una) y el seed funciona.

### Fase B1 — Notificaciones ⇄ F1

- [x] Modelo, migración `0008_notifications`, esquemas y `notification_service` (`notify`, `notify_admins`).
- [x] Rutas `/notifications`.
- [x] Engancharlas a lo existente: aprobar/rechazar establecimiento notifica al dueño.
- [x] Pruebas: listado, contador, marcar una y todas, aislamiento entre usuarios (404), `dedupe_key`, notificación al aprobar/rechazar.

### Fase B2 — Geolocalización y mapa ⇄ F2

- [x] Migración `0009_establishment_geo` y campos del modelo.
- [x] Validador común de ubicación (juntas o ninguna, área de servicio, `location_source`).
- [x] Coordenadas obligatorias en `POST /auth/restaurant/register`; campos de ubicación en perfil y reapply; `warnings` al aprobar sin ubicación.
- [x] `bounding_box` + `/nearby` con prefiltro SQL, filtros y `sort`.
- [x] `GET /establishments/map`.
- [x] `EstablishmentListItem` y `_LIST_LOAD_OPTIONS`; `GET /establishments` con `sort`, filtros y paginación **[BREAKING ⇄ F2]**.
- [x] **Adelantado de B3 (2026-11-12):** columnas `rating_count`, `rating_sum`, `rating_avg`, `ranking_score` + backfill en `0009` (no en `0010`), `rating_service` (`bayesian_score`, `relevance_score`, `recalculate_establishment_rating`, `recompute_all_ratings`), recálculo al crear reseña y `scripts/recompute_ratings.py`: el directorio, `/nearby` y `/map` de B2 ya ordenan y filtran por ellos y dejan de devolver reseñas.
- [x] Pruebas: el bounding box incluye/excluye correctamente; orden por distancia; `limit`; viewport inválido (400); `truncated`; solo `APPROVED`; ubicación fuera de área (400); lat sin lng (422); registro sin coordenadas (422).

### Fase B3 — Reseñas y puntuación ⇄ F3

- [x] Migración `0010_reviews_rating` (duplicados, restricciones). *(Agregados, backfill y `scripts/recompute_ratings.py` ya hechos en B2; aquí `recalculate_establishment_rating` pasa a contar solo reseñas `VISIBLE`.)* También crea ya las columnas de moderación de reseñas y respuestas (5.3) que usará B5, normaliza comentarios vacíos a `NULL` y recalcula los agregados.
- [x] `rating_service` (agregados, bayesiano, distribución, `category_rank`).
- [x] `check_can_review`; `POST /reviews/upload-url`; crear/listar/editar/eliminar; `GET /reviews/me`; límite diario.
- [x] Detalle con `recent_reviews`, `rating_distribution`, `viewer_review`, `viewer_can_review`, `category_rank` **[BREAKING ⇄ F3]**.
- [x] Rutas legadas marcadas `deprecated` y corregidas.
- [x] Pruebas (`tests/test_reviews_v2.py`): matriz de permisos (visitante 401, usuario sin teléfono 403, restaurante 403, admin 403, dueño 403, local no aprobado 404); duplicado 409; comentario opcional; imágenes de otro dominio 422 y más de 5 422; editar/eliminar ajena 404; edición de oculta 403; agregados y `ranking_score` correctos tras crear, editar, borrar, ocultar y restaurar; orden `ranking`; paginación y filtros; notificación al dueño; 429.
- **Notas de implementación (2026-11-13):**
  - `GET /restaurant/profile` y `POST`/`PATCH /establishments` (`EstablishmentResponse`) **también dejan de incluir `reviews`**: el panel tendrá `GET /restaurant/reviews` en B4. `Establishment.reviews` y `User.reviews` son `lazy="raise"`.
  - Errores de reseñas: `{"detail", ...}` con `code` en los 403 (`PHONE_NOT_VERIFIED`, `ROLE_NOT_ALLOWED`, `OWNER`, `SUSPENDED`, `HIDDEN`) y `review_id` en el 409.
  - `MyReview.comment` es el **texto original** del autor aunque esté bloqueado (`comment_blocked` y `moderation_notice` siguen indicando el bloqueo). `PATCH /reviews/{id}` responde `MyReview`.
  - `viewer_review_block` en la vista previa de un local no aprobado (dueño o admin) es el motivo de la cuenta o `ROLE_NOT_ALLOWED`.
  - `is_favorite` se añade en B7. La exposición del curso se actualizó: el vector de calificaciones del detalle se sustituyó por el vector de la distribución (`rating_service.py:97-98`).

### Fase B4 — Respuestas y horarios del establecimiento ⇄ F4

- [x] `GET /restaurant/reviews`, `/summary`, `PUT/DELETE …/reply` (upsert).
- [x] `schedule_service` (validación, solapes, medianoche, `is_open_at`) y `GET/PUT /restaurant/schedules`.
- [x] Pruebas (`tests/test_review_replies.py`, `tests/test_schedules.py`): responder dos veces actualiza (no 500); reseña de otro local 404; notificación solo al crear; `unanswered_count` y `response_rate`; horarios con solape 400; tramo que cruza medianoche; `is_open_at` en bordes (apertura incluida, cierre excluido, madrugada del día siguiente).
- **Notas de implementación (2026-11-13):** sin migración (no cambia el esquema).
  - `PUT …/reply` responde la reseña completa (`ReviewPublic`) con su respuesta; la notificación `REVIEW_REPLIED` usa `dedupe_key="review-replied:{id}"`, así que borrar y volver a responder no notifica otra vez. Responder una reseña oculta → 404. Si la respuesta está bloqueada, el panel ve el aviso (no su texto) también tras editarla.
  - El solape de horarios se comprueba en toda la semana: un tramo nocturno no puede invadir la mañana del día siguiente (incluido domingo → lunes). Las horas van en `HH:MM` (con segundos → 400). Un `PUT` rechazado no toca los horarios guardados; `[]` deja el local sin horarios.
  - `response_rate` es `null` si no hay reseñas visibles. La respuesta de la ruta legada `POST /reviews/{id}/reply` ahora limita el texto a 1000 caracteres, como `PUT`.

### Fase B5 — Administración y moderación ⇄ F5

- [x] Migración `0011_moderation`; estado `SUSPENDED` en usuarios y establecimientos; comprobación en `get_current_user` y login.
- [x] `moderation_service.record_moderation_action`.
- [x] Usuarios: listado paginado, detalle, rol con protecciones, suspender, reactivar, notificar.
- [x] Establecimientos: `reject` solo desde `PENDING`; `suspend`/`reactivate`; `PATCH` como admin; `catalog_router` compartido por `/restaurant` y `/admin/establishments/{id}`.
- [x] Reseñas, respuestas e imágenes: **bloquear/desbloquear comentario** (con categoría), bloquear/desbloquear respuesta, ocultar, restaurar y borrar con motivo; `to_public_review`/`to_public_reply` como única salida pública; cola de "editadas tras bloqueo" (`flagged_for_review`).
- [x] Reportes: crear, listar, resolver con acción (incluida `BLOCK_COMMENT`), descartar; notificaciones a admins, a quien reportó y al afectado; auto-ocultado opcional.
- [x] Bitácora y dashboard ampliado (añadir `blocked_comments` y `flagged_for_review` al dashboard).
- [x] Pruebas: usuario suspendido recibe 403 con cookie vigente y en login; el admin no se auto-suspende ni se quita el rol; último admin protegido; suspender local lo saca del directorio y del mapa (el aviso `PLAN_AFFECTED` a usuarios con planes queda para B6, cuando existan los planes); editar catálogo como admin deja bitácora y notifica; ocultar reseña recalcula el promedio y notifica; **bloquear comentario**: el detalle público, `GET /reviews/establishments/{id}`, `/restaurant/reviews` y `recent_reviews` devuelven `comment: null` + aviso, el promedio **no** cambia, el autor ve su texto original en `/reviews/me`, editar lo deja bloqueado con `flagged_for_review=True`, desbloquear lo publica; lo mismo para respuestas; reporte duplicado 409; resolver resuelve todos los reportes del destino; usuario normal recibe 403 en todo `/admin`.
- **Notas de implementación (2026-11-13):** migración `0011_moderation` (aplicada con copia `pre-0011_moderation`). 249 pruebas en verde (`test_admin_users.py`, `test_admin_establishment_management.py`, `test_admin_moderation.py`, `test_comment_blocking.py`, `test_reports.py`).
  - Servicios: `moderation_service` (bitácora, reseñas, respuestas, imágenes, productos, cola de reseñas), `admin_service` (nuevo: cuentas, establecimientos, dashboard) y `report_service`. **No hacen commit**: la ruta (o `resolve_report`) hace el único commit. Errores `ModerationError` (400/403/404/409/429) → `{"detail", ...extra}` en `app/main.py`; `AlreadyAppliedError` (409) cuando el destino ya está en ese estado, que `resolve_report` ignora para poder cerrar el reporte.
  - Cuenta suspendida: `AccountSuspendedError` → 403 `{"detail": "Tu cuenta está suspendida.", "code": "ACCOUNT_SUSPENDED", "reason"}` en `get_current_user` (también `/users/me`, `/auth/csrf`, `/notifications`), en el login (solo con la contraseña correcta, sin emitir cookie) y en `POST /auth/google/exchange`. `get_optional_current_user` la trata como visitante en las páginas públicas.
  - Usuarios: `GET /admin/users` → `Page[AdminUserListItem]` (incluye `establishment_id` de las cuentas `restaurant`); `open_reports_count` cuenta reportes sobre la cuenta y sobre sus reseñas. `PATCH …/role`, `suspend` y `reactivate` responden `AdminUserListItem` (superconjunto de `UserResponse`); `notify` responde `204`. `reactivate` y los demás "restaurar" aceptan cuerpo opcional `{"note"}`.
  - Establecimientos: `GET /admin/establishments` sigue siendo una lista (no `Page`); `open_reports_count` cuenta reportes sobre el local, sus fotos, su menú y sus respuestas. El detalle añade ubicación, `price_range`, `ranking_score` y `suspension_reason`. Un local `SUSPENDED` recibe 403 `{"detail": "Establecimiento suspendido", "status": "SUSPENDED"}` en todo el panel (también `PATCH /restaurant/profile`), ve `suspension_reason` en `/restaurant/status` y no puede re-aplicar (409).
  - `catalog_router.build_catalog_router(dep, audit=)`: la dependencia devuelve `(actor, establecimiento)`. Con `audit=True` el `EDIT_CATALOG` se agrega antes de la operación (si falla con 400/404/409 no se confirma nada) y el aviso al dueño usa `dedupe_key="admin-catalog-edit:{id}:{fecha local}"` (uno por día). El admin gestiona locales en cualquier estado. Extra: `POST /admin/establishments/{id}/upload-url?folder=`.
  - Moderación: las acciones responden `AdminReviewItem` (texto original de reseña y respuesta, autor con email, local y `open_reports_count`); los `DELETE` exigen `?reason=` (5..1000) y responden `204`. `hide` acepta `reason` o `note`. Bloquear el comentario de una reseña sin texto → 400 (usar borrar imagen u ocultar); volver a bloquear un comentario reescrito (`flagged_for_review`) lo confirma bloqueado. Filtro `flagged_for_review` y contador del dashboard incluyen reseñas cuya **respuesta** se reescribió tras un bloqueo; `blocked_comments` suma reseñas y respuestas. `sort=most_reported` en `GET /admin/reviews`.
  - Acciones de bitácora añadidas a la lista de 5.5: `DELETE_REPLY`, `HIDE_MENU_ITEM`, `DELETE_MENU_ITEM`. Los motivos de suspensión al resolver un reporte son la `note` o, sin ella, la etiqueta de la categoría.
  - Reportes: el destino `USER` es visible si no está suspendido. El duplicado (mismo usuario y destino) es 409 aunque el reporte anterior ya esté cerrado (restricción única). Con el destino ya borrado, `resolve` con acción → 404 y `preview.exists=false`; con `NONE` o `dismiss` se cierra. Descartar también avisa a quienes reportaron (`REPORT_RESOLVED`, "no encontramos una infracción").
  - Dashboard: `scheduled_plans` es 0 hasta B6.
  - Seed: cuenta `admin1@demo.planati.test`, dos comentarios bloqueados (uno reescrito y pendiente), una reseña oculta por spam, una respuesta bloqueada, dos reportes abiertos, el último usuario y un local suspendidos (todo con la bitácora y las notificaciones de los servicios reales). `down` borra también la bitácora del admin demo.

### Fase B6 — Planes y recordatorios ⇄ F6

- [x] Migración `0012_plans`, modelos, esquemas, `plan_service`.
- [x] Rutas `/plans` y `GET /plans/{id}/calendar.ics` (`calendar_service`).
- [x] `reminder_service` (recordatorios, cierre de planes con invitación a reseñar, purga) y `app/workers/reminders.py` con `lifespan`; `scripts/run_reminders.py`.
- [x] Pruebas: total calculado en servidor (ignora cualquier total del cliente); ítem de otro local 400; ítem no disponible 400; fuera de horario 400; tramo de medianoche válido; sin offset 422; recordatorio en el pasado 400; `PATCH` recalcula total y reinicia el recordatorio; plan ajeno 404; `dispatch_due_reminders` envía una sola vez aunque se llame dos veces; no envía si el plan ya pasó; `complete_past_plans` marca `COMPLETED` y crea `REVIEW_PROMPT` (con `?review=1`) solo si no hay reseña; `price_changed` cuando cambia el precio; el `.ics` tiene `CRLF`, texto escapado, horas en UTC, `VALARM` solo con recordatorio, `STATUS:CANCELLED` en planes cancelados y 404 para planes ajenos.
- **Notas de implementación (2026-11-13):** migración `0012_plans` (aplicada con copia `pre-0012_plans`). 277 pruebas en verde (`test_plans.py`, `test_reminders.py`, `test_calendar_ics.py`).
  - Errores `PlanError` (400/403/404/409/429) → `{"detail", ...extra}`: `code` en los 403 (`ROLE_NOT_ALLOWED`, `PHONE_NOT_VERIFIED`) y en algunos 400 (`CLOSED`, `REMINDER_IN_PAST`, `INVALID_ITEMS` con `invalid_item_ids`, `ESTABLISHMENT_UNAVAILABLE`).
  - `scheduled_at` se guarda en UTC redondeado al minuto. Un local **sin horarios** no restringe la hora. Las respuestas traen las fechas en UTC (`…Z`).
  - Ítems de la respuesta: `name`, `unit_price` (congelados), `quantity`, `subtotal`, `notes`, `current_price` (None si se borró o no está disponible) y `price_changed`; el detalle añade `prices_changed`, `establishment_available`, `outside_schedule`, `reminder_sent_at`. `items_count` es el número de líneas.
  - `GET /plans`: `from` y `to` van juntos (uno solo → 400), con zona (sin offset → 422), `to > from` y máximo 92 días; sin ellos, los próximos (todos los estados, salvo `status=`). Orden ascendente; `limit` hasta 100.
  - `PATCH` y cancelar: solo `SCHEDULED` y futuros (409). Con el local ya no aprobado, `PATCH` → 400 `ESTABLISHMENT_UNAVAILABLE` (cancelar y eliminar siguen permitidos). `title: ""`/`null` vuelve al título por defecto; `party_size`, `scheduled_at` o `items` en `null` → 422; `establishment_id` se ignora.
  - Suspender un local (B5) avisa `PLAN_AFFECTED` a los usuarios con planes futuros `SCHEDULED` allí (el plan no se cancela solo). El dashboard ya cuenta `scheduled_plans`.
  - `.ics`: sin `VALARM` en planes cancelados; `Cache-Control: no-store`. `scripts/run_reminders.py` (`--once` o en bucle) y `app/workers/reminders.py` (`lifespan`). El recordatorio usa "hoy/mañana/el viernes 20 de noviembre a las HH:MM" en hora de Colombia.
  - Seed: 4 planes demo (user1: próximo con platos y recordatorio + uno completado; user2: mañana + uno cancelado), en horas en que el local abre.

### Fase B7 — Favoritos y tipo de establecimiento ⇄ F7

- [x] Migración `0013_favorites`; rutas `/favorites`; `is_favorite` en el detalle.
- [x] `establishment_type` editable desde el perfil del restaurante y por el admin; filtros ya listos desde B2.
- [x] Pruebas: favorito idempotente; solo aprobados; aislamiento entre usuarios.
- **Notas de implementación (2026-11-13):** migración `0013_favorites` (aplicada con copia `pre-0013_favorites`). 283 pruebas en verde (`test_favorites.py`).
  - `establishment_type` ya era editable desde B2 (`PATCH /restaurant/profile`) y B5 (`PATCH /admin/establishments/{id}`, con auditoría); no hubo cambios.
  - Solo rol `user` activo y con teléfono verificado (`require_favorites_user`): 403 `{"detail", "code"}` con `ROLE_NOT_ALLOWED` o `PHONE_NOT_VERIFIED`. Errores `FavoriteError` manejados en `app/main.py`.
  - `PUT` → 404 si el local no existe o no está `APPROVED`; si ya era favorito no cambia la fecha. `DELETE` siempre 204 (también sobre locales suspendidos).
  - Un favorito de un local que deja de estar aprobado se conserva pero no se lista (ni en `/favorites` ni en `/favorites/ids`) y vuelve si se reactiva.
  - Orden: el guardado más recientemente primero; `limit` 1..50.
  - Extra no previsto en 7.8: `GET /favorites/ids` → `{"establishment_ids": [...]}` para marcar el corazón en las tarjetas del directorio, cercanos y mapa sin añadir `is_favorite` a cada listado.
  - Seed: user1 con 3 favoritos (uno es el local suspendido, que no se lista) y user2 con 1.

### Fase B8 — Privacidad y datos personales ⇄ F8

> Puede adelantarse después de B1, pero **debe estar terminada antes de publicar la app**. Va aquí porque la exportación y la eliminación de la cuenta tocan todos los modelos anteriores.

- [x] Migración `0014_privacy`, modelo `Consent`, settings de versiones (`DataRequest` no: era opcional).
- [x] `GET /legal/versions`, `GET/POST /users/me/consents`, `pending_consents` en `UserResponse`.
- [x] Aceptación obligatoria en `POST /auth/register` y `POST /auth/restaurant/register` (actualizar `restaurant_payload()` y los demás payloads de prueba).
- [x] Comprobación `CONSENT_REQUIRED` en `require_active_user`, `require_admin` y `require_restaurant_user`; actualizar `create_user` en `conftest.py` para que los usuarios de prueba nazcan con las versiones vigentes.
- [x] `GET /users/me/export`, `POST /users/me/delete/send-code`, `DELETE /users/me`.
- [ ] Opcional: `data_requests` con días hábiles y cola del admin. **No implementado**: la política de datos debe indicar un correo de contacto para consultas y reclamos.
- [x] Consentimientos en el seed.
- [x] Pruebas: registro sin aceptar → 422; versión vieja → 409; cuenta con versión vieja recibe 403 `CONSENT_REQUIRED` en rutas protegidas pero puede usar `/users/me` y aceptar; tras aceptar queda el historial con canal; exportación contiene los datos del usuario y no los de otros; eliminación con contraseña y con código SMS; la eliminación borra reseñas y recalcula los promedios afectados; `restaurant`/`admin` no se auto-eliminan (409).
- **Notas de implementación (2026-11-13):** migración `0014_privacy` (aplicada con copia `pre-0014_privacy`). 302 pruebas en verde (`test_privacy.py`). Probada también sobre Postgres en una base temporal (subida, bajada, seed y eliminación real).
  - **[BREAKING ⇄ F8]** Los registros exigen los cuatro campos de aceptación (sin `is_adult`, D10) y todas las cuentas creadas antes de `0014` quedan con `pending_consents` y reciben 403 `CONSENT_REQUIRED` en las rutas protegidas hasta llamar a `POST /users/me/consents`. En local, `seed_demo down` + `up` deja las cuentas demo al día.
  - `CONSENT_REQUIRED` (403 `{"detail", "code", "pending_consents"}`) se exige también en `require_reviewer`, `require_planner` y `require_favorites_user` (y, a través de `require_admin`, en `get_establishment_for_admin`). Errores `PrivacyError` manejados en `app/main.py`.
  - Canal de `POST /users/me/consents`: `GOOGLE_COMPLETE_PROFILE` si la cuenta es de Google y no tiene historial; si no, `RE_ACCEPTANCE`. Es idempotente (si ya están las vigentes no inserta filas). Responde el `UserResponse` actualizado.
  - Exportación: perfil, consentimientos, reseñas (texto original aunque esté bloqueado, imágenes y respuesta visible del local), planes con ítems, favoritos, reportes hechos y notificaciones de 90 días. 429 con `retry_after_seconds`; la marca es `users.last_data_export_at`.
  - `DELETE /users/me`: cuerpo `{"confirmation": "ELIMINAR", "password"}` o `{..., "code"}` (exactamente uno, si no 422); contraseña o código incorrectos → 400; 204 y cookie borrada. El código viene de `POST /users/me/delete/send-code` (400 sin teléfono verificado; mismo enfriamiento y límites del OTP). Efectos y trazabilidad en 7.9.
  - Las lápidas de cuentas demo eliminadas no las borra `seed_demo down` (su correo ya no es `@demo.planati.test`).

### Fase B9 — Revisión de seguridad antes de publicar ⇄ F9

> **Pendiente: no se ejecuta mientras el MVP sea solo local.** Se hace cuando el equipo decida publicar la app. La parte de código de CSRF, cookies, validación al arrancar y la copia local ya se hizo en B0; aquí se cierra lo de despliegue y operación.

- [ ] Decidir la topología (D12) y configurar dominio, HTTPS, redirección y HSTS; si la API va en otro subdominio, `ACCESS_TOKEN_COOKIE_DOMAIN`.
- [ ] Generar `SECRET_KEY` de producción (9.3) y cargar todos los secretos en el hosting; comprobar que la app no arranca con valores inseguros.
- [ ] CORS de producción con orígenes, métodos y cabeceras explícitos; `ENABLE_API_DOCS=false`.
- [ ] Ampliar `scripts/backup_db.py` con cifrado, subida al bucket privado y retención 7/4/6 (9.4.2); programarlo a diario; copia antes de cada migración.
- [ ] Primera restauración de prueba completa y registrada.
- [ ] `docs/OPERACION.md` y la sección 7 actualizada de `GUIA_AUTENTICACION_COOKIE_HTTPONLY.md`.
- [ ] Indicar en la política de datos (7.9) el plazo de conservación de las copias.
- [ ] Ejecutar la lista de verificación de 9.5 en el entorno publicado y guardar el resultado.
- **Hecho cuando:** toda la lista de 9.5 está marcada en el servidor real.

### Fase B10 — Opcional / futuro

- PostGIS: columna `geography(Point, 4326)` sincronizada desde lat/lng, índice GIST, `ST_DWithin`/`ST_Distance` cuando `DATABASE_URL` sea PostgreSQL (mantener el camino portable para SQLite).
- Web Push con VAPID (`pywebpush`) aprovechando el service worker existente del frontend.
- Limpieza de imágenes huérfanas en R2 (objetos de `reviews/` sin referencia tras 24 h).
- `slowapi` para límite de peticiones por IP en login, reseñas y reportes.
- Reservas confirmadas por el establecimiento (si se elige en D1).

---

## 13. Pruebas: criterios generales

- Cada endpoint nuevo tiene al menos: caso feliz, sin sesión (401), rol incorrecto (403), recurso ajeno (404) y validación (422/400).
- Los servicios con lógica pura (`bounding_box`, `bayesian_score`, `is_open_at`, `relevance`) tienen pruebas unitarias sin base de datos.
- Las pruebas de tiempo usan un `now` explícito (nunca `datetime.now()` dentro de la aserción).
- Tras completar las fases, probar migraciones de punta a punta contra PostgreSQL (`docker compose up -d`, `alembic upgrade head`, `alembic downgrade 0007_restaurant_catalog`, `alembic upgrade head`) y ejecutar el seed.

## 14. Criterios de aceptación

1. Un restaurante registrado con ubicación aparece en `/establishments/map` y `/nearby` en cuanto el admin lo aprueba.
2. `/establishments` y `/map` responden sin cargar reseñas; el orden por defecto es por `ranking_score`.
3. Un usuario verificado publica una reseña con solo estrellas, o con texto e imágenes; no puede publicar una segunda; puede editarla y eliminarla; el promedio, el conteo y el ranking se actualizan en la misma petición.
4. Restaurantes, admins y dueños no pueden reseñar; nadie puede reseñar un local no aprobado.
5. El establecimiento responde, edita y elimina su respuesta desde `/restaurant/reviews`; el autor recibe una notificación.
6. El admin gestiona usuarios (suspender, reactivar, rol, avisar), establecimientos (aprobar, rechazar, suspender, reactivar, editar perfil y catálogo) y contenido (ocultar, restaurar, borrar), resuelve reportes y todo queda en la bitácora; el afectado es notificado.
7. Un usuario crea un plan con platos y cantidades, ve el total calculado por el servidor, lo consulta por rango de fechas y recibe el recordatorio en la bandeja de notificaciones a la hora configurada, una sola vez.
8. El plan se descarga como `.ics` válido (se importa en Apple Calendar con su alarma) y, al completarse, el usuario recibe la invitación a reseñar.
9. El admin bloquea el comentario de una reseña: en público y en el panel del establecimiento aparece "El comentario fue bloqueado por una violación a las políticas de la aplicación.", las estrellas siguen contando, el autor es notificado con la categoría y ve su texto original.
10. Nadie crea una cuenta sin aceptar la política de datos y los términos vigentes; la aceptación queda registrada con versión, fecha y canal; el usuario puede descargar sus datos y eliminar su cuenta.
11. Los horarios se guardan y validan en hora de Colombia; el seed crea datos demo coherentes en Cúcuta.
12. Toda petición que cambia estado con cookie de sesión exige un origen permitido y un `X-CSRF-Token` válido; la app no arranca en modo producción con una clave secreta débil ni con configuración insegura; en local existe `scripts/backup_db.py` y se probó una restauración completa. (La cookie solo por HTTPS en un servidor real y las copias cifradas fuera del equipo se verifican en B9, al publicar.)
13. `pytest` en verde; migraciones aplicadas en PostgreSQL; `README.md`, `CLAUDE.md` y `.env.example` actualizados.

## 15. Riesgos y notas

| Riesgo | Mitigación |
|---|---|
| Cambios de forma en `/establishments` y en el detalle rompen el frontend actual. | Marcados **[BREAKING]**; desplegar B2/B3 junto con F2/F3. |
| Diferencias SQLite/PostgreSQL (offset de fechas, `FOR UPDATE`, `::float`). | Fechas siempre en UTC; SQL específico de PostgreSQL solo dentro de migraciones; pruebas de servicios con `now` fijo. |
| Varios workers ejecutando el ciclo de recordatorios. | `dedupe_key` única + `skip_locked`; o un único ejecutor por cron. |
| Mover `haversine_km` cambia las líneas citadas en la exposición del curso. | No moverlo; si cambian las líneas, actualizar `docs_aparte_back/PlanATi_Exposicion_8min.md`. |
| Coordenadas obligatorias bloquean el registro si el mapa no carga. | El frontend ofrece GPS del navegador (no depende de Google) y entrada manual. |
| Activar CSRF rompe el frontend actual (sus `POST`/`PATCH`/`DELETE` no envían token). | B0 y F0 se despliegan juntos; el frontend reintenta una vez pidiendo un token nuevo si recibe `CSRF_FAILED`. |
| En producción las rutas protegidas redirigen siempre al login. | Elegir la topología D12 antes de publicar y verificarla con la lista de 9.5. |
| Perder la base local (`docker compose down -v`, reinstalar Docker, migración que borra datos). | Copia local antes de cada migración y de cambios destructivos (9.4.1). |

---

## 16. Decisiones

**Confirmadas por el equipo (2026-11-12):** horarios editables, tipo de establecimiento (D5), favoritos, invitación a reseñar tras el plan, Google Calendar + `.ics`, protección de la clave de Google Maps, zona horaria America/Bogota, datos demo en Cúcuta, aviso de privacidad y autorización de datos, bloqueo del comentario por moderación, revisión de seguridad antes de publicar (CSRF, cookie solo por HTTPS, clave secreta fuerte, copias de seguridad).

**Pendientes (valor por defecto aplicado):**

| Id | Pregunta | Por defecto en este plan | Alternativa |
|---|---|---|---|
| D1 | ¿El plan es personal o una **solicitud de reserva** que el establecimiento confirma o rechaza? | Personal (agenda del usuario). | Reserva: añadir `PENDING_CONFIRMATION`/`CONFIRMED`/`DECLINED`, vista de reservas en `/restaurant` y notificaciones cruzadas. |
| D2 | ¿Una reseña por usuario y establecimiento, o una por visita? | Una, editable. | Varias con un intervalo mínimo (p. ej. 30 días) entre reseñas del mismo usuario. |
| D3 | ¿Ubicación obligatoria al registrar el establecimiento? | Sí. | Opcional, con aviso en el panel y al aprobar. |
| D4 | ¿El admin edita directamente el perfil y catálogo de un establecimiento? | Sí, con bitácora y notificación al dueño. | Solo ocultar/desactivar y pedir al dueño que corrija. |
| D5 | ~~¿Tipos de establecimiento?~~ **Confirmado.** | `establishment_type`; el rol interno sigue siendo `restaurant`. | Más adelante, tabla de categorías administrable por el admin. |
| D6 | ¿Moderación previa (las reseñas esperan aprobación) o posterior? | Posterior (se publican al instante y se moderan por reportes). | Previa para usuarios nuevos o reseñas con imágenes. |
| D7 | ¿Ocultar automáticamente con N reportes? | Desactivado (`REPORT_AUTO_HIDE_THRESHOLD=0`). | Activarlo con 3–5. |
| D8 | ¿Recordatorios fuera de la app? | En la app + la alarma del `.ics` en el calendario del teléfono. | Web Push (B10), correo o SMS (el proveedor SMS ya existe). |
| D9 | ~~Al eliminar su cuenta, ¿se borran las reseñas del usuario o se anonimizan?~~ **Confirmado (2026-11-13).** | Se borran y se recalculan los promedios, sin romper la trazabilidad: la cuenta queda como lápida anonimizada y la bitácora, los reportes y los consentimientos se conservan sin datos personales (7.9). | Anonimizar autor y conservar estrellas y texto. |
| D10 | ~~¿Edad mínima para registrarse?~~ **Confirmado (2026-11-13).** | Sin edad mínima: solo se declara aceptar la política de tratamiento de datos y los términos. Nota legal: si se registran menores, el art. 7 de la Ley 1581 y el art. 12 del Decreto 1377 exigen la autorización de su representante; los textos legales deben mencionarlo (lo revisa la universidad o un asesor). | Declarar ser mayor de edad (18 años). |
| D11 | Con el comentario bloqueado, ¿las estrellas siguen contando en el promedio? | Sí (solo se retira el texto). | No contarlas mientras esté bloqueado. |
| D12 | ¿Cómo se publican frontend y API? | **MVP: solo local** (`localhost:3000` y `localhost:8000`; no aplica). Al publicar, se recomienda mismo dominio: `https://<dominio>` y `https://<dominio>/api/v1` mediante *reverse proxy* o `rewrites` de Next.js. | API en `api.<dominio>` con `ACCESS_TOKEN_COOKIE_DOMAIN=<dominio>`. |
| D13 | ¿Dónde se aloja PostgreSQL? (define cómo se hacen las copias) | **MVP: Docker Compose local** con `scripts/backup_db.py` (9.4.1). Al publicar, se recomienda PostgreSQL administrado con copias automáticas + volcado semanal propio. | Servidor propio con `scripts/backup_db.py` diario. |

---

## 17. Por planificar (no implementar todavía)

Propuestas registradas el 2026-11-12. **No forman parte del alcance** hasta que el equipo las apruebe; al aprobar una, convertirla en una fase con tareas, contratos y pruebas como las anteriores.

| Propuesta | Idea para el backend | Valor |
|---|---|---|
| **Recuperar contraseña por SMS** | `POST /auth/password/forgot` (correo o teléfono; respuesta genérica para no revelar si la cuenta existe) envía un código al teléfono verificado reutilizando el proveedor SMS; `POST /auth/password/reset` (código + nueva contraseña) cambia la contraseña e invalida las sesiones abiertas (columna `session_version` en `users` incluida en el JWT). Límites de intentos como el OTP actual. | Hoy quien olvida la contraseña no puede volver a entrar. |
| **Vista previa al compartir (WhatsApp, redes)** | Endpoint público ligero `GET /establishments/{id}/summary` (nombre, categoría, puntuación, portada, dirección) para que el frontend genere metadatos Open Graph en el servidor; `sitemap` de establecimientos aprobados. | Los enlaces compartidos mostrarían foto y nombre del lugar. |
| **Reseña con "visita verificada"** | `verified_visit` en `reviews`: verdadero si el autor tenía un plan `COMPLETED` en ese local antes de la reseña; se calcula al crear o editar. | Más confianza en las reseñas. |
| **Filtro automático de groserías** | Lista de términos en español (incluidas expresiones regionales), normalizando tildes y sustituciones (`4`→`a`); al crear o editar una reseña o respuesta, si coincide, `flagged_for_review=True` (no se bloquea sola) y aparece en la cola del admin. Lista editable más adelante desde la consola. | Detecta contenido indebido antes de que alguien lo reporte. |
| **Festivos y horarios especiales** | Tabla `special_schedules` (fecha, cerrado u horario propio, nota) y bandera "abre festivos" usando el paquete `holidays` (Colombia); `is_open_at` la tiene en cuenta al validar planes. | Evita planes en días en que el local cierra. |
| **Estadísticas para el establecimiento** | Tabla `establishment_events` (vista de perfil, clic en "Cómo llegar", clic en teléfono, plan creado, favorito) agregada por día, sin guardar datos de quién; `GET /restaurant/stats?from&to`. Mencionarlo en la política de datos. | Argumento para atraer negocios a la plataforma. |
