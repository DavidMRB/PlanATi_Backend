# PlanATi: guía rápida para la exposición (8 minutos)

> Apoyo para presentar el proyecto y explicar cómo aplicamos los temas de las guías 6, 7, 8, 9 y 10 de Diseño Funcional.
> Las rutas de las guías 6 a 8 corresponden al backend (`PlanATi_Backend`, rama `main`, commit `7455428`).
> Las de las guías 9 y 10 corresponden al código actual de la rama `dev` (backend y `PlanATi_Frontend`, 13 de noviembre de 2026).


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

## 10. Pruebas

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

