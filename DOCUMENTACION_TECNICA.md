# PlanATi: guía rápida para la exposición (8 minutos)

> Apoyo para presentar el proyecto y explicar cómo aplicamos los temas de las guías 1, 2, 3, 4, 5, 6, 7, 8, 9, 10 y 11 de Diseño Funcional.
> Las rutas de las guías 6 a 8 corresponden al backend (`PlanATi_Backend`, rama `main`, commit `7455428`).
> Las de las guías 9 y 10 corresponden al código actual de la rama `dev` (backend y `PlanATi_Frontend`, 13 de noviembre de 2026).
> Ampliación documental: 27 de noviembre de 2026, backend `dev`, base `2e994fd`. La numeración sigue las guías solicitadas: **Guía 3 (condiciones y validaciones)**, **Guía 4 (cadenas y listas)** y **Guía 5 (operaciones con información)**.
> Se conserva el guion original; las guías añadidas son material de apoyo para seleccionar durante la exposición de 8 minutos. Sus referencias usan **archivo + función o clase**, porque las líneas cambian al añadir comentarios. Las referencias numéricas y resultados de pruebas originales son históricos.


---

## 1. Qué es PlanATi

PlanATi es una plataforma web para **descubrir establecimientos gastronómicos de Cúcuta** (cafés, bares y restaurantes). Hoy esa información está repartida entre Instagram, TikTok, Google Maps y WhatsApp; PlanATi la reúne en un solo lugar: ubicación, horarios, menú, fotos y reseñas.

**Idea clave:** *Cúcuta no necesita más lugares, necesita una mejor forma de descubrirlos.*

## 2. Cómo funciona

Hay tres tipos de usuario:

| Actor | Qué hace |
|---|---|
| **Usuario** | Se registra (correo o Google), verifica su teléfono con un código SMS, busca lugares por nombre o categoría, ve los cercanos y publica reseñas de 1 a 5 estrellas. |
| **Restaurante** | Crea su cuenta junto con su establecimiento. Queda en estado `PENDING` hasta que un administrador lo aprueba; luego gestiona su perfil, sus fotos y su catálogo de productos y combos. |
| **Administrador** | Aprueba o rechaza restaurantes (`PENDING → APPROVED / REJECTED`), cambia roles y ve estadísticas. |

**Regla importante:** el directorio público **solo muestra establecimientos aprobados**.

---

## 3. Stack tecnológico y por qué

| Capa | Tecnología | Para qué la usamos | Por qué la elegimos |
|---|---|---|---|
| Frontend | **Next.js 16 + React 19** | Páginas, rutas y componentes | Componentes reutilizables y buen rendimiento web |
| | **TypeScript** | Tipado del código | Detecta errores antes de ejecutar |
| | **Tailwind CSS 4** | Estilos | Identidad visual consistente y rápida de construir |
| Backend | **Python 3.13 + FastAPI** | API REST en `/api/v1` | Es el lenguaje del curso, es asíncrono y genera documentación automática (`/docs`) |
| | **Pydantic** | Validación de datos | Rechaza datos inválidos (error 422) sin escribir validaciones a mano |
| | **SQLAlchemy 2 (async)** | Acceso a la base de datos | Trabaja con clases de Python en lugar de SQL suelto |
| | **Alembic** | Migraciones | Versiona los cambios de la base de datos |
| Datos | **PostgreSQL + PostGIS** (Docker) | Base de datos | Robusta y con soporte geográfico para crecer |
| Servicios | **Cloudflare R2** | Fotos | Almacenamiento económico; el navegador sube directo |
| | **Google OAuth** | Inicio de sesión con Google | Menos fricción para registrarse |
| | **SMS con código OTP** | Verificar teléfono | Cuentas reales y menos spam |
| Seguridad | **JWT en cookie HttpOnly + Argon2** | Sesión y contraseñas | El token no es accesible desde JavaScript; contraseñas con hash seguro |
| Calidad | **pytest + SQLite** | Pruebas automáticas | Pruebas rápidas sin levantar PostgreSQL |

## 4. Arquitectura y decisiones

```
Frontend (Next.js) ──JSON + cookie──▶ Rutas ─▶ Esquemas ─▶ Servicios ─▶ Modelos ─▶ PostgreSQL
                                     (HTTP)   (Pydantic)  (lógica)    (SQLAlchemy)
```

- **Capas separadas:** las rutas reciben y responden, los servicios deciden y los modelos guardan. Así cada parte se prueba y se cambia por separado.
- **Sesión en cookie HttpOnly:** el token nunca viaja en la URL ni queda expuesto a JavaScript.
- **Restaurantes con aprobación:** se evita publicar negocios falsos.
- **Imágenes con URL firmada:** la foto no pasa por nuestro servidor, sino que va directo a R2.
- **Cercanía con haversine en Python:** es suficiente para el MVP; PostGIS queda listo para consultas espaciales cuando crezca.

---

## 4.1. Guía 1 · Paradigmas, archivo Python y salida con `print()`

**Conceptos:** un paradigma es una forma de organizar la solución de un problema. La programación imperativa describe pasos y cambios de estado; la funcional transforma datos mediante funciones; la orientación a objetos agrupa datos y comportamiento en clases. Un archivo Python es un módulo de texto con extensión `.py`; `print()` escribe en la salida estándar, normalmente la terminal.

### Cómo lo aplicamos

| Tema | Ejemplo aplicado | Dónde |
|---|---|---|
| Paradigma de programación | El backend combina funciones de servicio, instrucciones imperativas y clases para modelos y esquemas; no sigue un único paradigma puro. | `app/services/establishment_service.py`, `create_establishment`; `app/schemas/establishment.py`, `MenuItemInput` |
| Programación funcional | `map(catalog_row, combos)` transforma cada combo en una fila de Excel. `haversine_km` calcula una distancia a partir de sus argumentos sin modificar registros. Son usos de estilo funcional dentro de una aplicación con efectos como guardar datos. | `app/services/excel_service.py`, `menu_workbook`; `app/services/establishment_service.py`, `haversine_km` |
| Programación imperativa | Crear el objeto, añadirlo a la sesión, confirmar y refrescar son instrucciones ordenadas que modifican el estado almacenado. | `app/services/establishment_service.py`, `create_establishment` |
| Archivo Python | `scripts/run_reminders.py` contiene importaciones, una función `main` y la entrada `if __name__ == "__main__"`; se ejecuta como módulo con `python -m scripts.run_reminders --once`. | `scripts/run_reminders.py` |
| `print()` | El script muestra cuántos recordatorios envió, planes completó y notificaciones purgó en una pasada. | `scripts/run_reminders.py`, `main` |

**Ejemplo 1: instrucciones imperativas** (fragmento de `create_establishment`, después de construir el objeto):

```python
session.add(establishment)
await session.commit()
await session.refresh(establishment)
return establishment
```

**Ejemplo 2: transformación funcional** (fragmentos de `menu_workbook`):

```python
def catalog_row(item: MenuItem) -> tuple:
    return (item.id, item.name, item.description, item.price, "Sí" if item.is_available else "No", item.image_url)

_write_sheet(combos_sheet, f"Combos · {name}", columns, map(catalog_row, combos), formats={4: PRICE_FORMAT})
```

**Ejemplo 3: salida de consola real** (`scripts/run_reminders.py`, `main`):

```python
result = await run_once()
print(
    f"Recordatorios enviados: {result['reminders']}, planes completados: {result['completed']}, "
    f"notificaciones purgadas: {result['purged']}."
)
```

### Lo que no aplicamos

| Tema o uso | Por qué no | Alternativa aplicada y ejemplo |
|---|---|---|
| Paradigma funcional puro para todo el backend | Guardar registros, enviar mensajes y responder peticiones requieren efectos externos. | Servicios asíncronos con una sesión explícita: `session.add(establishment)` y `await session.commit()` en `create_establishment`. |
| `print()` para mostrar información al usuario web | Esa salida aparece en la terminal del servidor, no en el navegador. | La ruta `search_establishments`, en `app/api/routes/establishments.py`, devuelve `await list_establishments(...)`; FastAPI genera JSON mediante `response_model=list[EstablishmentListItem]`. El frontend presenta los datos. |

---

## 4.2. Guía 2 · Variables, tipos de datos y operadores

**Conceptos:** una variable asocia un nombre con un valor. `int` representa enteros, `float` números de punto flotante, `str` texto y `bool` verdadero o falso. Las anotaciones describen los tipos esperados; Pydantic y FastAPI validan los datos recibidos. Los operadores permiten calcular y comparar; las condiciones deciden qué instrucciones ejecutar.

### Cómo lo aplicamos

| Tema | Ejemplo aplicado | Dónde |
|---|---|---|
| Variable | `radius_km = 6371.0` conserva el radio terrestre usado para calcular distancias. | `app/services/establishment_service.py`, `haversine_km` |
| `int` | `skip: int = 0` y `limit: int = 20` controlan la paginación; `day_of_week: int` identifica el día de 0 a 6. | `establishment_service.py`, `list_establishments`; `app/schemas/establishment.py`, `ScheduleInput` |
| `float` | Coordenadas, radios y distancia de `haversine_km`; `radius_km = 6371.0`. | `establishment_service.py`, `haversine_km` |
| `str` | `search: str`, nombres y categorías; `pattern = f"%{search.strip()}%"` construye una búsqueda. | `establishment_service.py`, `list_establishments` |
| `bool` | `approved_only: bool = True` activa el filtro de aprobados; `is_combo` e `is_available` describen productos. | `establishment_service.py`, `list_establishments`; `app/schemas/establishment.py`, `MenuItemResponse` |
| Operadores aritméticos | `-`, `/`, `**`, `+` y `*` calculan la distancia en `haversine_km`; `%` alterna el fondo de las filas de Excel con `index % 2 == 1`. | `establishment_service.py`, `haversine_km`; `app/services/excel_service.py`, `_write_row` |
| Operadores de comparación | `distance <= radius_km`, `sort == "rating"`, `len(digits) != 10` y `radius_km > 0` comparan valores. `is None` comprueba ausencia por identidad. | `establishment_service.py`, `list_nearby_establishments`; `phone_verification_service.py`, `normalize_colombian_phone`; `rating_service.py`, `relevance_score` |
| Operadores lógicos | `and`, `or` y `not` combinan o niegan condiciones al validar el área de servicio. Se desarrolla su aplicación en la Guía 3. | `establishment_service.py`, `ensure_in_service_area` |

**Ejemplo: variable, tipo y cálculo** (`haversine_km`; fragmentos):

```python
radius_km = 6371.0
delta_lat = lat2_rad - lat1_rad
delta_lon = lon2_rad - lon1_rad
```

`radius_km` es una variable `float`; las restas calculan diferencias angulares. La función combina división `/`, potencia `**`, suma `+` y multiplicación `*` para devolver la distancia. En `list_nearby_establishments`, `distance <= radius_km` compara esa distancia con el radio solicitado.

### Lo que no aplicamos

| Tema o uso | Por qué no | Alternativa aplicada y ejemplo |
|---|---|---|
| `float` para dinero | La representación binaria puede introducir errores de precisión decimal. | `price: Decimal = Field(ge=0, decimal_places=2)` en `MenuItemInput`; `_build_items` calcula y redondea el total con `Decimal("0.01")`. `float` sí se usa para distancias. |
| Validar datos leyendo `input()` en un ciclo | Los datos llegan por peticiones web y atender una consola bloquearía ese flujo. | `EstablishmentCreate` valida el JSON; por ejemplo, un nombre de un carácter incumple `min_length=2` y FastAPI responde 422. |
| División entera `//` en el cálculo de distancia citado | La distancia necesita conservar la parte decimal. | `delta_lat / 2` y `delta_lon / 2` usan división real en `haversine_km`. |

---

## 4.3. Guía 3 · Condiciones, operadores lógicos y validaciones de entrada

**Conceptos:** `if` ejecuta un bloque si la condición se cumple; `if else` elige entre dos caminos; `if elif else` evalúa alternativas en orden. `and` exige que se cumplan ambas condiciones, `or` acepta alguna y `not` niega el resultado. Una condición anidada se evalúa dentro de otra.

### Cómo lo aplicamos

| Tema | Ejemplo aplicado | Dónde |
|---|---|---|
| `if` | `if approved_only:` agrega el filtro de estado solo cuando se solicita. | `establishment_service.py`, `list_establishments` |
| `if else` | `if args.once:` ejecuta una pasada; `else:` mantiene el ciclo de recordatorios. | `scripts/run_reminders.py`, `main` |
| `if elif else` | Si una celda recibe texto se guarda como texto; si recibe una fecha se convierte a hora local; en otro caso se asigna el valor directamente. | `app/services/excel_service.py`, `_write_row` |
| Operadores lógicos: `and`, `or`, `not` | `not (south <= float(latitude) <= north and west <= float(longitude) <= east)` detecta una ubicación fuera del área. El `or` permite salir si falta una coordenada o la configuración del área. | `establishment_service.py`, `ensure_in_service_area` |
| Condiciones anidadas | Dentro de `if "scheduled_at" in changes:`, otro `if` comprueba si realmente cambió la fecha antes de validarla. | `app/services/plan_service.py`, `update_plan` |
| Validaciones de entrada | `Field(ge=0, le=6)` limita el día; `Field(min_length=2, max_length=150)` limita el nombre; la normalización del teléfono rechaza números que no tengan diez dígitos nacionales o no comiencen en 3. | `app/schemas/establishment.py`, `ScheduleInput` y `EstablishmentCreate`; `phone_verification_service.py`, `normalize_colombian_phone` |

**Ejemplo 1: decisión con tres alternativas** (`excel_service.py`, `_write_row`; fragmento):

```python
if isinstance(value, str):
    cell.value = ILLEGAL_CHARACTERS_RE.sub("", value)
    cell.data_type = "s"
elif isinstance(value, datetime):
    cell.value = to_local(value).replace(tzinfo=None)
    cell.number_format = DATE_FORMAT
else:
    cell.value = value
```

**Ejemplo 2: lógica y validación** (`establishment_service.py`, `ensure_in_service_area`; fragmento):

```python
if latitude is None or longitude is None or settings.service_area is None:
    return
south, west, north, east = settings.service_area
if not (south <= float(latitude) <= north and west <= float(longitude) <= east):
    raise OutOfServiceAreaError(OUT_OF_SERVICE_AREA_MESSAGE)
```

La ubicación debe cumplir **ambos** rangos (`and`); `not` invierte esa condición para rechazarla. El primer `if` omite la comprobación cuando falta información o no hay un área configurada.

**Ejemplo 3: dos caminos** (`scripts/run_reminders.py`, `main`; esquema del flujo existente):

```python
if args.once:
    # Ejecuta run_once() y muestra el resumen con print().
    ...
else:
    # Ejecuta reminders_loop(stop) hasta la cancelación.
    ...
```

**Ejemplo 4: condiciones anidadas** (`plan_service.py`, `update_plan`; fragmento):

```python
if "scheduled_at" in changes:
    scheduled_at = normalize_scheduled_at(changes["scheduled_at"])
    if scheduled_at != ensure_utc(plan.scheduled_at):
        _check_window(scheduled_at, now)
        _check_open(establishment, scheduled_at)
```

La condición externa comprueba que se envió la fecha y la interna que cambió; solo entonces se validan la ventana permitida y el horario del establecimiento.

### Lo que no aplicamos

| Tema o uso | Por qué no | Alternativa aplicada y ejemplo |
|---|---|---|
| Pedir repetidamente datos con `input()` hasta que sean válidos | La entrada proviene de peticiones web; cada petición debe recibir su respuesta. | `EstablishmentCreate` usa `name: str = Field(min_length=2, max_length=150)`; FastAPI rechaza un nombre de un carácter con 422. `normalize_colombian_phone` lanza `PhoneVerificationError` si la longitud o el prefijo no son válidos. |

---

## 4.4. Guía 4 · Variables alfanuméricas, cadenas y listas

**Conceptos:** una variable alfanumérica guarda texto (`str`), aunque incluya números. Las cadenas y listas tienen posiciones que comienzan en **0**; un índice consulta un elemento y un segmento (`inicio:fin`) obtiene una parte. Una lista conserva un orden y permite añadir elementos.

### Cómo lo aplicamos

| Tema | Ejemplo aplicado | Dónde |
|---|---|---|
| Variables alfanuméricas | `phone_number` y `digits` son cadenas: un teléfono es un identificador, no una cantidad para sumar; `normalized_email` conserva el correo normalizado. | `app/services/phone_verification_service.py`, `normalize_colombian_phone`; `app/services/auth_service.py`, `register_user` |
| Operaciones con cadenas | `email.strip().lower()` quita espacios externos y unifica mayúsculas; `re.sub` deja dígitos; `startswith`, `len` y una f-string validan y reconstruyen el teléfono. | `auth_service.py`, `register_user`; `phone_verification_service.py`, `normalize_colombian_phone` |
| Listas | `nearby = []` acumula pares de lugar y distancia con `append`; `combos = [item for item in items if item.is_combo]` filtra el catálogo. | `app/services/establishment_service.py`, `list_nearby_establishments`; `app/services/excel_service.py`, `menu_workbook` |
| Posiciones e índices | En cada tupla `item`, `item[0]` es el establecimiento y `item[1]` la distancia; `nearby[:limit]` selecciona los primeros resultados de la lista. | `establishment_service.py`, `list_nearby_establishments` |
| Segmentos de cadena | `digits[2:]` retira los dos caracteres del indicativo `57`; se aplica solo si la cadena comienza con ese indicativo. | `phone_verification_service.py`, `normalize_colombian_phone` |
| Consulta de elementos | La prueba de exportación consulta `book["Productos"]` y después la celda `["B3"]` para comprobar el nombre almacenado. La API consulta establecimientos por su `id`. | `tests/test_excel_exports.py`, `test_menu_export_includes_own_products_and_combo_components`; `establishment_service.py`, `get_establishment` |

**Ejemplo: limpiar, consultar un segmento y generar texto** (`normalize_colombian_phone`):

```python
digits = re.sub(r"[^\d]", "", phone_number)
if digits.startswith("57"):
    digits = digits[2:]
if len(digits) != 10 or not digits.startswith("3"):
    raise PhoneVerificationError("Número de teléfono inválido")
return f"+57{digits}"
```

Con `phone_number = "57 300 123 4567"`, `digits` termina en `"3001234567"` y el resultado es `"+573001234567"`.

**Ejemplo: lista, consulta por posición y segmento** (`list_nearby_establishments`; fragmentos):

```python
nearby: list[tuple[Establishment, float]] = []
# Dentro del recorrido y después de comprobar el radio:
nearby.append((establishment, distance))
# Después de recorrer los establecimientos:
nearby.sort(key=lambda item: item[1])
```

La función aplica después el criterio adicional solicitado y retorna `nearby[:limit]`. La posición 1 pertenece a la **tupla**; el segmento se aplica a la **lista**. No se confunde la posición con el identificador de base de datos.

### Lo que no aplicamos

| Tema o uso | Por qué no | Alternativa aplicada y ejemplo |
|---|---|---|
| Lista global como almacenamiento definitivo | Su contenido se perdería al reiniciar y cada proceso podría tener una versión diferente. | `create_establishment` usa `session.add(establishment)` y `await session.commit()` para persistir en PostgreSQL. Las listas locales sirven para procesar resultados. |
| Usar la posición de una lista como identificador de un registro | Ordenar o filtrar cambia las posiciones. | `get_establishment` consulta `.where(Establishment.id == establishment_id)`, una identidad estable. |

---

## 4.5. Guía 5 · Operaciones con la información

**Concepto:** una aplicación recibe datos, los valida, realiza operaciones y devuelve resultados; cuando deben conservarse, los registra en almacenamiento persistente. PlanATi aplica este flujo mediante formularios web, rutas de API, servicios y PostgreSQL.

### Cómo lo aplicamos

| Operación | Ejemplo aplicado | Dónde |
|---|---|---|
| Registrar información | `register_user` normaliza correo y teléfono, construye `User` y lo añade a la sesión; `create_establishment` construye y guarda un establecimiento. | `app/services/auth_service.py`, `register_user`; `app/services/establishment_service.py`, `create_establishment` |
| Consultar información | `get_establishment` consulta por `id` y retorna el primer resultado o `None`. | `establishment_service.py`, `get_establishment` |
| Mostrar información almacenada | `search_establishments` retorna los establecimientos y su `response_model` los convierte a JSON para la interfaz. También se muestran en hojas Excel. | `app/api/routes/establishments.py`, `search_establishments`; `app/services/excel_service.py`, `menu_workbook` |
| Buscar información | `list_establishments` construye `f"%{search.strip()}%"` y usa `ilike` sobre nombre o categoría. | `establishment_service.py`, `list_establishments` |
| Calcular un valor | `_build_items` suma precio por cantidad y devuelve el total decimal del plan. | `app/services/plan_service.py`, `_build_items` |
| Validar información | `normalize_colombian_phone` rechaza teléfonos inválidos; `EstablishmentCreate` limita nombres y coordenadas antes de guardarlos. | `app/services/phone_verification_service.py`, `normalize_colombian_phone`; `app/schemas/establishment.py`, `EstablishmentCreate` |
| Clasificar información | `menu_workbook` separa productos y combos según `is_combo`, y los escribe en hojas diferentes. | `app/services/excel_service.py`, `menu_workbook` |
| Actualizar información | `update_establishment` extrae solo campos enviados con `model_dump(exclude_unset=True)`, los asigna y confirma la transacción. | `establishment_service.py`, `update_establishment` |
| Determinar el estado de un registro | `list_establishments` comprueba el estado `APPROVED` al filtrar lo visible; `STATUS_LABELS` presenta el estado como «Pendiente», «Aprobado», «Rechazado» o «Suspendido» en Excel. | `establishment_service.py`, `list_establishments`; `excel_service.py`, `STATUS_LABELS` y `establishments_workbook` |
| Realizar una operación | `cancel_plan` comprueba que el plan esté programado y cambia su estado a `CANCELLED`, confirmando la actualización. | `app/services/plan_service.py`, `cancel_plan` |
| Generar un resultado a partir de los datos ingresados | Las coordenadas y el radio recibidos producen una lista de lugares cercanos con su distancia; los productos y cantidades elegidos producen un total calculado por el servidor. | `establishment_service.py`, `list_nearby_establishments`; `plan_service.py`, `_build_items` |

**Ejemplo 1: actualizar solo lo ingresado** (`update_establishment`; fragmento):

```python
values = data.model_dump(exclude_unset=True)
schedules = values.pop("schedules", None)
menu_items = values.pop("menu_items", None)
for field, value in values.items():
    setattr(establishment, field, value.strip() if isinstance(value, str) else value)
```

Si el formulario solo envía `{"price_range": "$$$"}`, el recorrido modifica ese campo; los horarios y el menú se procesan aparte si fueron enviados. La función confirma los cambios con `await session.commit()`.

**Ejemplo 2: calcular y generar un resultado** (`_build_items`; fragmento):

```python
total = sum((row.unit_price_snapshot * row.quantity for row in built), Decimal("0"))
return built, total.quantize(Decimal("0.01"))
```

Para un producto de 24.000 COP con cantidad 2, el total es 48.000,00 COP. El precio se obtiene del catálogo y queda congelado en el ítem del plan; no se confía en un total enviado por el navegador.

### Lo que no aplicamos

| Tema o uso | Por qué no | Alternativa aplicada y ejemplo |
|---|---|---|
| Menú de consola con opciones para registrar, consultar y actualizar | PlanATi atiende usuarios desde un navegador y necesita conservar datos entre sesiones. | `GET /api/v1/establishments` consulta el directorio; `GET /api/v1/restaurant/profile` y `PATCH /api/v1/restaurant/profile` consultan y actualizan el perfil del restaurante autorizado en `app/api/routes/restaurant.py`. |
| Mostrar todos los registros con un `print()` | El usuario web no ve la terminal y una tabla grande requiere límites. | `search_establishments` recibe `skip` y `limit` y responde JSON; las exportaciones autorizadas generan un archivo descargable cuando se necesita una hoja completa. |

---

## 5. Guía 6 · Ciclos

**Concepto:** un ciclo repite instrucciones. `for` recorre una secuencia; `while` repite mientras se cumpla una condición; `break` corta el ciclo; `continue` salta a la siguiente iteración.

### Cómo lo aplicamos

| Concepto | Lo usamos para | Dónde |
|---|---|---|
| `for` | Recorrer los establecimientos y calcular su distancia al usuario | `app/services/establishment_service.py:105` |
| `continue` | Saltar los lugares que no tienen coordenadas | `establishment_service.py:107` |
| `if` dentro del ciclo | Conservar solo los que están dentro del radio | `establishment_service.py:115` |
| `for` sobre `.items()` | Aplicar solo los campos editados al actualizar | `establishment_service.py:159` |

**Ejemplo** (búsqueda de cercanos, simplificado):

```python
for establishment in establishments:
    if establishment.latitude is None or establishment.longitude is None:
        continue                      # sin coordenadas: se omite
    distance = haversine_km(latitude, longitude, lat_del_lugar, lng_del_lugar)
    if distance <= radius_km:         # condición dentro del ciclo
        nearby.append((establishment, distance))
```

### Lo que no aplicamos

| Tema | Por qué no | Alternativa |
|---|---|---|
| `while` / menú `while True` | Un servidor web no espera a que alguien escriba en la consola; eso lo bloquearía para los demás usuarios. | **Uvicorn** mantiene su propio ciclo escuchando peticiones y **cada opción del menú es una ruta** de la API (`app/main.py:69-76`). |
| `break` | No hay menú de consola que cerrar ni una búsqueda manual que cortar. | La base de datos devuelve directamente el registro buscado. |
| Ciclos anidados | Los datos sí tienen niveles (establecimiento → menú → combos → productos), pero no hace falta recorrerlos a mano. | **SQLAlchemy** los carga en una sola consulta con `selectinload` (`establishment_service.py:34-40`) y **Pydantic** los convierte a JSON anidado. |

---

## 6. Guía 7 · Cadenas, listas, tuplas y diccionarios

**Conceptos:**
- **Cadena (`str`):** texto; se limpia con `strip()`, `lower()`, etc.
- **Lista (`list`):** colección ordenada y modificable.
- **Tupla (`tuple`):** colección ordenada que no se puede modificar.
- **Diccionario (`dict`):** pares clave → valor.

### Cómo lo aplicamos

| Estructura | La usamos para | Dónde |
|---|---|---|
| `str` | Normalizar el correo con `strip().lower()`: `Laura@Correo.COM` y `laura@correo.com` son el mismo usuario | `app/services/auth_service.py:26` |
| `list` | Horarios, menú, reseñas e imágenes de cada establecimiento | `app/models/establishment.py:86` |
| `tuple` | Par inmutable `(establecimiento, distancia)` | `establishment_service.py:116` |
| `dict` | Cada registro y cada respuesta viajan como JSON (clave → valor) | `app/api/routes/users.py:75` |
| `set` *(extra)* | Validar que un rol pertenezca a `{"user", "admin"}` | `app/api/routes/admin.py:68` |

**Ejemplo 1: índices y segmentos de cadena** (normalizar un teléfono colombiano):

```python
digits = re.sub(r"[^\d]", "", phone_number)   # "300 123 4567" -> "3001234567"
if digits.startswith("57"):
    digits = digits[2:]                          # segmento: quita el indicativo
if len(digits) != 10 or not digits.startswith("3"):
    raise PhoneVerificationError("Número de teléfono inválido")
return f"+57{digits}"                            # "+573001234567"
```
*`app/services/phone_verification_service.py:21-27`*

**Ejemplo 2: diccionario para una actualización parcial:**

```python
values = data.model_dump(exclude_unset=True)   # {"price_range": "$$$"}: solo lo enviado
for field, value in values.items():
    setattr(establishment, field, value.strip() if isinstance(value, str) else value)
```
*`establishment_service.py:155-160`*. El `id` no se puede cambiar porque no está en el esquema de actualización.

### Lo que no aplicamos

| Tema | Por qué no | Alternativa |
|---|---|---|
| `input()` | El backend no tiene a nadie escribiendo en su consola. | Los datos llegan como **JSON** y **Pydantic** valida tipos y rangos (`app/schemas/establishment.py:55-64`). |
| `print()` para mostrar | Solo se vería en la terminal del servidor. | La API responde **JSON** y el frontend lo muestra en pantalla. |
| Lista en memoria `registros = []` | Se perdería al reiniciar el servidor y no se compartiría entre usuarios. | Tabla en **PostgreSQL**: `session.add()` hace el papel de `append()` (`establishment_service.py:144`). |
| `title()` / `upper()` | `title()` dañaría nombres propios (`McDonald's` → `Mcdonald'S`) y ningún campo necesita mayúsculas. | Para comparar sin mayúsculas se usa `ilike` en la base de datos. |

---

## 7. Guía 8 · Vectores: almacenamiento, ordenamiento y búsqueda

**Conceptos:**
- **Vector:** estructura unidimensional con posiciones; en Python es una lista.
- **Ordenamiento:** `sort()` ordena la misma lista; `sorted()` crea una nueva; `key=lambda` indica el criterio y `reverse=True` invierte el sentido.
- **Búsqueda secuencial:** recorrer uno por uno hasta encontrar el elemento.

### Cómo lo aplicamos

| Concepto | Lo usamos para | Dónde |
|---|---|---|
| Vector + `range()` + `zip()` | Distribución de estrellas: posición *i* = reseñas de *i + 1* estrellas, p. ej. `[1, 1, 0, 2, 1]` | `app/services/rating_service.py:97-98` |
| `sort()` + `lambda` (ascendente) | Ordenar los cercanos del más próximo al más lejano | `establishment_service.py:119` |
| Orden en la base de datos (ascendente) | Directorio en orden alfabético por nombre (`GET /establishments?sort=name`) | `establishment_service.py:196` |
| Orden descendente | Panel admin: solicitudes más recientes primero | `app/services/restaurant_service.py:48` |
| Búsqueda por atributo | Nombre o categoría, sin importar mayúsculas ni espacios | `establishment_service.py:62-68` |
| Rango + primeros N *(reto)* | Solo los lugares dentro del radio y los primeros según el límite | `establishment_service.py:115-124` |

**Ejemplo: el vector de calificaciones**

```python
# rows = {1: 1, 2: 1, 4: 2, 5: 1}  ← conteos por estrella que devuelve la base de datos
counts = [int(rows.get(stars, 0)) for stars in range(1, 6)]           # [1, 1, 0, 2, 1]
return {str(stars): count for stars, count in zip(range(1, 6), counts)}
# sum(counts) = 5 reseñas; el promedio se guarda ya calculado en el establecimiento (rating_avg)
```

**Ejemplo: ordenar con `lambda` y tomar los primeros**

```python
nearby.sort(key=lambda item: item[1])   # item = (establecimiento, distancia)
return nearby[:limit]                   # los N más cercanos
```

### Lo que no aplicamos

| Tema | Por qué no | Alternativa |
|---|---|---|
| Búsqueda secuencial **por id** con `for` | Habría que cargar todos los registros en memoria para recorrerlos. | Consulta por **llave primaria indexada** en PostgreSQL: el detalle o un **404** si no existe (`app/api/routes/establishments.py:124-136`). |
| Búsqueda por texto con `lower()` en un `for` | Mismo problema de memoria. | `strip()` y luego `ilike '%texto%'` en la base de datos. |
| El usuario elige ascendente o descendente | **Pendiente.** Cada listado usa hoy el orden más útil para su propósito. | Propuesta: parámetro `?order=asc` o `?order=desc` en `GET /establishments`. |

**Regla general:** ordenamos en **Python** lo que se calcula durante la petición (distancias, conteos de estrellas) y en la **base de datos** lo que abarca toda la tabla (nombre, fecha).

---

## 8. Guía 9 · Matrices: creación, recorrido y operaciones

**Conceptos:**
- **Matriz:** estructura bidimensional de filas y columnas; en Python es una lista de listas.
- **Acceso:** primero la fila y luego la columna (`matriz[i][j]`); con la misma notación se modifica.
- **Recorrido:** dos ciclos `for` anidados, uno para las filas y otro para las columnas.
- **Operaciones:** totales por fila o por columna, total general y promedio.
- **Matrices especiales:** cuadrada, nula e identidad.

### Cómo lo aplicamos

La matriz del proyecto es el **horario semanal** de cada establecimiento: **7 filas (lunes a domingo) × hasta 3 tramos** (por ejemplo, 11:00–15:00 y 18:00–22:00).

| Concepto | Lo usamos para | Dónde |
|---|---|---|
| Matriz (lista de listas) | `WeekSchedule = Segment[][]`: fila = día, columna = tramo | `PlanATi_Frontend/components/establishment-management/schedules.ts:11` |
| Creación | Matriz de 7 filas vacías (`emptyWeek`) que se llena con lo que devuelve la API (`weekFromSchedules`) | `schedules.ts:33-45` |
| Registro y consulta | El restaurante edita y guarda su horario (`PUT` / `GET /restaurant/schedules`); el detalle público muestra la fila de cada día | `app/api/routes/catalog_router.py:186-191`; `PlanATi_Frontend/app/(site)/establishments/[id]/page.tsx:283-294` |
| Acceso `[fila][columna]` | Leer o cambiar la apertura o el cierre de un tramo | `PlanATi_Frontend/components/establishment-management/SchedulesEditor.tsx:166-199` |
| Ciclos anidados | Validar cada tramo de cada día (frontend) y comparar cada par de tramos para detectar solapamientos (backend, Python) | `schedules.ts:66-86`; `app/services/schedule_service.py:81-82` |
| Operaciones | Tramos por día (máx. 3), días abiertos, total del plan = Σ precio × cantidad, promedio de estrellas = suma / conteo | `schedule_service.py:64-78`; `SchedulesEditor.tsx:123`; `app/services/plan_service.py:147`; `app/services/rating_service.py:67-82` |
| Integración | Saber si el local está abierto, avisar si un plan queda fuera de horario y generar las franjas cada 30 min del asistente de planes | `schedule_service.py:89-106`; `plan_service.py:398`; `PlanATi_Frontend/components/plans/slots.ts:48-62` |

**Ejemplo: recorrido anidado en Python** (detectar tramos que se solapan):

```python
intervals = [(item, _week_interval(item)) for item in items]   # (tramo, [inicio, fin) en minutos)
for index, (item, interval) in enumerate(intervals):            # fila: cada tramo
    for other, other_interval in intervals[index + 1 :]:         # columna: los tramos siguientes
        if _overlaps(interval, other_interval):
            raise ScheduleValidationError(f"Los horarios se solapan: {_describe(item)} y {_describe(other)}.")
```
*`app/services/schedule_service.py:80-86`*. También detecta un tramo nocturno (sábado 18:00–02:00) que invade la madrugada del domingo.

**Ejemplo: la matriz del horario**

```ts
// fila = día, columna = tramo
week = [
  [{ opening_time: "11:00", closing_time: "15:00" }, { opening_time: "18:00", closing_time: "22:00" }], // lunes
  [],                                                                                                   // martes: cerrado
  ...
]
week[0][1].closing_time   // "22:00": lunes, segundo tramo
```

### Lo que no aplicamos

| Tema | Por qué no | Alternativa |
|---|---|---|
| Matriz cuadrada | Los días no tienen el mismo número de tramos; habría que rellenar celdas vacías sin significado. | **Matriz irregular** de 7 filas × 0 a 3 tramos (`schedules.ts:11`). |
| Matriz nula | Llenar con ceros sería ambiguo: 00:00 es una hora válida. | **Semana vacía**: 7 filas sin tramos = local sin horario (`emptyWeek`, `schedules.ts:33-35`). |
| Matriz identidad | Es de álgebra lineal; no multiplicamos ni invertimos matrices. | No se necesita. |
| `input()` + `float()` + `try/except` | El servidor no lee de la consola. | **Formulario web** y validación en el servidor: respuesta **400** con el motivo (`schedule_service.py:61-86`). |
| `print()` de la matriz con formato | Solo se vería en la terminal del servidor. | El editor y la página del local muestran la matriz como **tarjetas por día** (`SchedulesEditor.tsx:135-166`). |
| Total por columna con `[i][j]` | Recorrer toda la tabla en Python es más lento con muchos datos. | **Diccionario** por día y **`GROUP BY`** en SQL (`schedule_service.py:64-78`, `rating_service.py:67-76`). |

---

## 9. Guía 10 · Subalgoritmos: funciones, procedimientos y modularización

**Conceptos:**
- **Subalgoritmo:** bloque de instrucciones con una tarea específica; en Python, una función (`def`).
- **Función:** recibe parámetros y devuelve un resultado con `return`.
- **Procedimiento:** realiza una tarea sin devolver un valor (en Python, una función que retorna `None`).
- **Lambda:** función corta de una sola expresión; muy usada como criterio de ordenamiento.
- **Paso de argumentos:** un objeto mutable (lista, diccionario, objeto) modificado dentro de la función cambia fuera de ella; reasignar el parámetro no afecta al original.
- **Variables locales y globales:** se recomienda preferir parámetros y retornos en lugar de globales.

### Cómo lo aplicamos

| Concepto | Lo usamos para | Dónde |
|---|---|---|
| Modularización | Cada operación del negocio es una función agrupada por tema: 17 módulos en `app/services/` (registrar, consultar, buscar, actualizar, calificar) | `app/services/` |
| Función con `return` | Distancia entre dos coordenadas (`haversine_km`), puntuación bayesiana (`bayesian_score`), relevancia = puntuación + cercanía (`relevance_score`), área de búsqueda (`bounding_box`), ¿está abierto? (`is_open_at`) | `establishment_service.py:15`, `:215`; `rating_service.py:17`, `:31`; `schedule_service.py:89` |
| Procedimiento (`-> None`) | Actualizar los promedios de un local, validar horarios o zona de servicio (lanzan excepción si algo falla), escribir la cookie de sesión, impedir arrancar con configuración insegura | `rating_service.py:58`; `schedule_service.py:61`; `establishment_service.py:207`; `app/core/security.py:46`; `app/core/startup_checks.py:103` |
| `lambda` | Ordenar los cercanos por distancia, calificación o relevancia, y los horarios por día y hora | `establishment_service.py:119-123`; `schedule_service.py:110` |
| Argumento mutable | `apply_aggregates(establishment, …)` modifica el establecimiento recibido y el cambio persiste fuera | `rating_service.py:58-62` |
| Reasignar el parámetro | `_apply_filters(query, …)` reasigna `query` en cada filtro y la devuelve; la consulta del llamador no cambia | `establishment_service.py:240-253` |
| Variables locales | `radius_km`, `a` y `c` solo existen dentro de `haversine_km`; `nearby` es una lista local de la búsqueda | `establishment_service.py:15-30`, `:102` |
| Global de solo lectura | `settings`: la configuración se crea una vez y solo se lee | `app/core/config.py:139` |

**Ejemplo: función que llama a otra dentro de una lambda**

```python
def relevance_score(ranking_score, distance_km, radius_km, *, weight=None) -> float:
    w = settings.relevance_rating_weight if weight is None else weight
    score = bayesian_score(0, 0) if ranking_score is None else ranking_score
    closeness = 1 - min(distance_km / radius_km, 1) if radius_km > 0 else 0
    return w * (score - 1) / 4 + (1 - w) * closeness          # 0 = peor, 1 = mejor

nearby.sort(key=lambda item: -relevance_score(item[0].ranking_score, item[1], radius_km))
```
*`rating_service.py:31-36` y `establishment_service.py:123`*. Una sola función sirve para la búsqueda y para las pruebas.

**Ejemplo: procedimiento que modifica el objeto recibido**

```python
def apply_aggregates(establishment: Establishment, count: int, total: int) -> None:
    establishment.rating_count = count
    establishment.rating_sum = total
    establishment.rating_avg = round(total / count, 2) if count else None
    establishment.ranking_score = bayesian_score(total, count)    # no hay return
```
*`rating_service.py:58-62`*

### Lo que no aplicamos

| Tema | Por qué no | Alternativa |
|---|---|---|
| Procedimiento con `print()` | Solo se vería en la terminal del servidor. | El procedimiento **modifica estado o lanza una excepción**; la ruta responde **JSON** y los avisos van al *logging* (`startup_checks.py:103-111`). |
| Palabra `global` / lista global `productos = []` | Varias peticiones al mismo tiempo compartirían y pisarían los datos; además se perderían al reiniciar. | La **sesión de base de datos** llega como parámetro, inyectada con `Depends(get_db)` (`app/api/routes/establishments.py:47`). |
| `calcular_total_inventario()` con `total +=` | Habría que cargar todas las reseñas en memoria. | `COUNT` y `SUM` en SQL y luego `apply_aggregates` (`rating_service.py:39-55`). |
| `try/except ValueError` al leer con `input()` | No hay consola. | **Pydantic** valida tipos y rangos y responde **422** (`app/schemas/establishment.py`). |
| `mostrar_menu()` + `iniciar_programa()` + `if __name__ == "__main__"` | El servidor no espera a que alguien elija una opción. | Cada opción es una **ruta** de la API; **Uvicorn** arranca `app/main.py` y la función `lifespan` controla el inicio y el cierre. |

---

## 9.1. Guía 11 · Exportación de datos usando Excel

**Conceptos:** exportar es convertir datos del sistema en un archivo que pueda usarse fuera de la aplicación. Un libro `.xlsx` contiene hojas; cada hoja organiza celdas en filas y columnas. PlanATi usa **openpyxl** para construir el libro y una respuesta HTTP para descargarlo.

### Cómo lo aplicamos

| Tema | Ejemplo aplicado | Dónde |
|---|---|---|
| Consultar datos para exportar | `export_menu` obtiene el catálogo y las imágenes de tipo `MENU`; `export_reviews` consulta las reseñas visibles para el panel y las convierte a su representación pública. | `app/services/excel_service.py`, `export_menu` y `export_reviews` |
| Crear un libro y sus hojas | `Workbook()` crea el libro; el menú se divide en `Productos`, `Combos`, `Composición` y, si hay imágenes, `Menú físico`. | `excel_service.py`, `menu_workbook` |
| Registrar filas y columnas | `_write_sheet` coloca el título en la fila 1, encabezados en la 2 y datos desde la 3; `_write_row` usa `sheet.cell(index, column)`. | `excel_service.py`, `_write_sheet` y `_write_row` |
| Dar formato | Precios con formato COP, fechas en hora local, anchos de columna, texto ajustado, encabezados de color y filas alternadas. | `excel_service.py`, `PRICE_FORMAT`, `DATE_FORMAT`, `_write_row` y `_write_sheet` |
| Facilitar la consulta | `freeze_panes = "A3"` mantiene las dos primeras filas visibles y `auto_filter.ref` habilita filtros sobre los encabezados y datos. | `excel_service.py`, `_write_sheet` |
| Exportar reseñas | La hoja `Reseñas` incluye autor público, puntuación, comentario, fecha y respuesta; respeta los avisos de moderación y no recupera texto bloqueado para mostrarlo. | `excel_service.py`, `export_reviews` y `reviews_workbook` |
| Exportar establecimientos | La hoja administrativa contiene estado, tipo, contacto, puntuación, reportes y coordenadas; conserva los filtros de búsqueda y estado solicitados. | `excel_service.py`, `establishments_workbook`; `app/api/routes/admin.py`, `export_admin_establishments` |
| Generar la descarga | `BytesIO` guarda el archivo en memoria y `Response` lo entrega con el tipo MIME de Excel y `Content-Disposition: attachment`. | `excel_service.py`, `_download` |
| Controlar permisos | El restaurante exporta su propio menú y reseñas con `require_approved_restaurant`; el administrador exporta establecimientos con `require_admin` y datos de un local con `get_establishment_for_admin`. | `app/api/routes/restaurant.py`, `export_restaurant_menu` y `export_restaurant_reviews`; `app/api/routes/admin.py`, rutas de exportación |
| Conservar texto como texto | `_write_row` limpia caracteres no admitidos y fuerza `cell.data_type = "s"` para que un nombre como `=1+1` se almacene como texto, sin convertirse en fórmula. | `excel_service.py`, `_write_row` |

**Ejemplo 1: crear las hojas del menú** (`menu_workbook`; fragmento):

```python
book = Workbook()
products = book.active
products.title = "Productos"
combos_sheet = book.create_sheet("Combos")
components = book.create_sheet("Composición")
```

Los productos y combos contienen ID, nombre, descripción, precio, disponibilidad e imagen (URL); `Composición` detalla cada producto y cantidad de los combos. La hoja opcional `Menú físico` exporta **enlaces a imágenes**, no imágenes incrustadas.

**Ejemplo 2: generar y descargar el archivo** (`_download`; fragmento):

```python
with BytesIO() as output:
    book.save(output)
    content = output.getvalue()
return Response(
    content=content,
    media_type=XLSX_MEDIA_TYPE,
    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"},
)
```

`menu_workbook` termina con `return _download(book, f"menu-establecimiento-{establishment_id}.xlsx")`. Las funciones que consultan la base de datos delegan la construcción del libro a `run_in_threadpool`, para ejecutar ese trabajo síncrono fuera del bucle asíncrono de la API.

### Rutas disponibles

Todas llevan el prefijo `/api/v1` y usan el método **GET**:

| Actor | Ruta | Resultado |
|---|---|---|
| Restaurante aprobado | `/restaurant/exports/menu.xlsx` | Menú de su propio establecimiento |
| Restaurante aprobado | `/restaurant/exports/reviews.xlsx` | Reseñas visibles de su propio establecimiento |
| Administrador | `/admin/exports/establishments.xlsx` | Directorio administrativo; acepta `status` y `search` |
| Administrador | `/admin/establishments/{establishment_id}/exports/menu.xlsx` | Menú del establecimiento seleccionado |
| Administrador | `/admin/establishments/{establishment_id}/exports/reviews.xlsx` | Reseñas visibles del establecimiento seleccionado |

**Ejemplo aplicado:** un administrador autenticado consulta `GET /api/v1/admin/exports/establishments.xlsx?status=APPROVED&search=Parrilla` y descarga `establecimientos-planati.xlsx` con los registros que cumplen esos filtros. `skip=0, limit=None` permite exportar los resultados completos de la consulta, sin limitarse a la página visible.

### Lo que no aplicamos

| Tema o uso | Por qué no | Alternativa aplicada y ejemplo |
|---|---|---|
| Automatizar la aplicación de escritorio Microsoft Excel | El servidor debe generar archivos sin depender de una aplicación instalada ni de una sesión gráfica. | `Workbook()` de openpyxl crea un `.xlsx` que después puede abrirse en Excel. |
| Guardar el archivo exportado en una ruta fija del servidor | La descarga se genera para una petición concreta y no necesita un archivo permanente compartido. | `_download` usa `BytesIO`, `book.save(output)` y `Response(content=content, ...)`. |
| Usar Excel como base de datos o importar cambios desde él | Esta funcionalidad es de exportación; las reglas, permisos y actualizaciones siguen en la API. | `export_menu` consulta los datos persistidos; las modificaciones del perfil se realizan mediante `PATCH /restaurant/profile` y PostgreSQL. |
| Fórmulas de Excel para calcular los valores exportados | Se exportan los valores del sistema, que ya aplica sus reglas en el servidor. | `catalog_row` escribe `item.price`; los totales de planes se calculan en `_build_items` con `Decimal`, y las puntuaciones con `rating_service`. |

**Pruebas existentes:** `tests/test_excel_exports.py` contiene cuatro pruebas sobre productos y combos propios, visibilidad de reseñas, permisos y filtros del administrador, y exportaciones del establecimiento seleccionado. También comprueba que `=1+1` siga siendo texto. Su presencia no implica una ejecución nueva en esta actualización documental.

---

## 10. Pruebas

**Nota de lectura:** los resultados siguientes se conservan del documento original y corresponden a sus revisiones históricas; no representan una ejecución actual ni el total de pruebas de la rama `dev` del 27 de noviembre de 2026. Para esta ampliación se comparan los tokens de código y el árbol sintáctico (AST) de cada archivo Python editado antes y después: solo se añaden comentarios, sin cambiar instrucciones, valores ni comportamiento. No se ejecutan procesos de recordatorios ni se modifica la base de datos.

| Suite | Resultado |
|---|---|
| Pruebas automáticas del repositorio (`pytest`) | **38 / 38** correctas |
| Escenarios de la Guía 7 (registro, consulta, modificación, condiciones) | **19 / 19** correctos |
| Escenarios de la Guía 8 (recorrido, orden ascendente y descendente, búsquedas, sin registros) | **15 / 15** correctos |
| Guía 9: pruebas de horarios (`tests/test_schedules.py`: tramos válidos, solapados, nocturnos, más de 3 por día) | **23 / 23** correctas (rama `dev`, 13 de noviembre de 2026) |
| Guía 10: pruebas de las funciones citadas (`test_rating_ranking.py`, `test_geo_nearby_map.py`, `test_schedules.py`: `bayesian_score`, `relevance_score`, `haversine_km`, `bounding_box`, `is_open_at`) | **46 / 46** correctas (rama `dev`, 13 de noviembre de 2026) |

Todas se ejecutan con **SQLite temporal**, sin tocar la base de datos real.

## 11. Cierre (frase final)

> PlanATi conecta a las personas que buscan qué hacer con los establecimientos que tienen algo que ofrecer. Técnicamente, aplicamos ciclos, estructuras de datos, ordenamiento, búsqueda, matrices y funciones **donde aportan valor real**, y cuando un ejemplo de consola no encaja en una aplicación web, usamos la alternativa correcta: rutas en lugar de menús, JSON en lugar de `input()`/`print()` y la base de datos en lugar de listas en memoria.

---

