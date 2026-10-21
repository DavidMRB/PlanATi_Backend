# Guía: autenticación con cookie HttpOnly y código OAuth de un solo uso

Esta guía describe cómo reemplazar la entrega del JWT en el JSON o en la URL por
una cookie `HttpOnly`. Para Google, usa además un código temporal de un solo uso
como puente entre el callback del backend y el frontend. No implementa cambios:
especifica el trabajo requerido en ambos proyectos.

## Objetivo y reglas de seguridad

- El JWT de sesión nunca debe aparecer en una URL, en `localStorage` ni en el
  JSON devuelto al frontend.
- El JWT se establece en una cookie `HttpOnly`; el navegador la envía
  automáticamente al backend.
- El callback de Google redirige al frontend con un código aleatorio temporal,
  no con el JWT.
- El código OAuth se guarda únicamente como hash, expira pronto y se consume
  atómicamente una sola vez.
- Las rutas autenticadas identifican la sesión mediante la cookie.
- La aplicación protege las operaciones que cambian estado contra CSRF.

## Flujo esperado

### Inicio de sesión y registro con correo

1. El frontend envía `POST /api/v1/auth/login` o `POST /api/v1/auth/register`
   con `credentials: "include"` (Fetch) o `withCredentials: true` (Axios).
2. El backend valida las credenciales, crea el JWT y lo establece en la cookie
   `access_token`.
3. El backend devuelve solo metadatos, por ejemplo
   `registration_complete` y `requires_phone_verification`; nunca devuelve el
   JWT.
4. El frontend decide a qué pantalla navegar según esos metadatos.
5. Las solicitudes posteriores, incluido `GET /api/v1/users/me`, incluyen la
   cookie automáticamente.

Para estos dos flujos no hace falta un código de un solo uso: la respuesta es
una llamada API directa entre el frontend y el backend, y el backend puede
establecer la cookie en esa respuesta.

### Inicio de sesión con Google

1. El frontend llama a `GET /api/v1/auth/google` incluyendo credenciales y
   luego navega el navegador a la `authorization_url` devuelta.
2. El backend establece la cookie OAuth `oauth_state` y redirige a Google.
3. Google vuelve a `GET /api/v1/auth/google/callback`.
4. El backend valida el `state`, intercambia el código de Google y autentica
   al usuario.
5. El backend crea un código aleatorio de un solo uso, guarda su hash con el
   usuario y su expiración, y redirige al frontend, por ejemplo:

   ```text
   http://localhost:3000/google-callback?code=<codigo-temporal>
   ```

6. La página `/google-callback` envía inmediatamente el código a
   `POST /api/v1/auth/google/exchange`, con credenciales incluidas.
7. El backend consume el código una sola vez, emite el JWT y lo establece en
   `access_token` como cookie `HttpOnly`. La respuesta contiene únicamente los
   metadatos de navegación.
8. El frontend elimina el parámetro `code` de la barra de direcciones y navega
   según `registration_complete`.

El código temporal no es un token de sesión y no debe permitir llamar a rutas
protegidas. Solo permite completar el intercambio una vez.

## Cambios en el backend

### 1. Configuración de cookies y frontend

Revisar `app/core/config.py` y las variables de entorno. La configuración debe
permitir definir como mínimo:

- URL de frontend usada para el callback OAuth (`FRONTEND_URL`).
- Nombre de cookie de sesión, si no se usa el nombre fijo `access_token`.
- Duración de la cookie, coordinada con la expiración del JWT.
- Política `SameSite` apropiada para los dominios de desarrollo y producción.

No construir destinos de redirección a partir de una URL arbitraria recibida
del navegador. Usar una URL configurada y confiable.

### 2. Utilidad común para crear y borrar la cookie

Crear una utilidad reutilizable para establecer la cookie en las respuestas de
login, registro y canje OAuth. Valores recomendados:

```text
key       = access_token
httponly  = true
secure    = true en producción con HTTPS
path      = /
max_age   = igual o menor que la duración del JWT
samesite  = Lax si frontend y API son same-site
```

En desarrollo HTTP local, `secure` debe poder ser `false`; en producción debe
ser `true`. Si frontend y API están en sitios distintos, el navegador puede
requerir `SameSite=None; Secure`. Preferir dominios propios same-site cuando
sea posible, porque las restricciones de cookies de terceros varían entre
navegadores.

Al cerrar sesión, `POST /api/v1/auth/logout` debe borrar la cookie usando el
mismo `path`, `domain` y demás atributos con que se creó. Si se mantienen JWT
stateless, borrar la cookie cierra la sesión del navegador, pero no invalida un
JWT que ya se haya copiado; usar una lista de revocación solo si el producto
requiere revocación inmediata.

### 3. Actualizar login y registro tradicionales

En `app/api/routes/auth.py`:

- Cambiar `login` y `register` para recibir la respuesta HTTP y establecer la
  cookie después de autenticar o crear al usuario.
- Dejar de serializar `access_token` en `TokenResponse`; devolver solo los
  metadatos funcionales de autenticación.
- Conservar las reglas actuales de registro completo y verificación telefónica.

Actualizar `app/schemas/auth.py` para que los modelos de respuesta de login y
registro no expongan el token.

### 4. Crear almacenamiento de códigos OAuth de un solo uso

Añadir un modelo y una migración Alembic, por ejemplo una tabla
`oauth_login_codes`, con campos equivalentes a:

- Identificador de fila.
- Identificador del usuario.
- Hash del código (`SHA-256` del valor aleatorio).
- Fecha de expiración.
- Fecha de consumo, inicialmente nula.
- Fecha de creación.

Generar el valor original con un generador criptográficamente seguro, por
ejemplo `secrets.token_urlsafe(32)`. Mostrarlo solo en la redirección al
frontend; nunca guardarlo en texto plano. Una expiración de 60 a 120 segundos
es suficiente para el canje.

El canje debe ser atómico. Actualizar la fila solo cuando coincida el hash, no
haya expirado y aún no esté consumida; marcarla consumida en esa misma
operación/transacción y continuar solo si exactamente una fila fue afectada.
Esto evita que dos solicitudes concurrentes canjeen el mismo código. Un código
ausente, expirado o ya consumido debe producir `401` o `400`, sin crear cookie
de sesión. Se pueden limpiar códigos expirados periódicamente, pero esa
limpieza no debe ser necesaria para validar el canje.

### 5. Separar callback de Google y canje del código

En `GET /api/v1/auth/google/callback`:

- Mantener la validación de `oauth_state`, el intercambio del código con Google
  y la autenticación del usuario.
- No incluir `access_token` en la URL.
- Crear y persistir el código temporal.
- Redirigir a la ruta configurada del frontend con solo `code` y, si hace
  falta, un identificador no sensible del resultado. Los metadatos de
  finalización deben obtenerse en el canje, no confiarse desde parámetros
  modificables del navegador.
- Eliminar la cookie `oauth_state` también en la respuesta de redirección.

Añadir `POST /api/v1/auth/google/exchange`:

- Recibir el código temporal en el cuerpo, no en la URL del endpoint.
- Validar y consumir el código atómicamente.
- Cargar el usuario y emitir un JWT nuevo.
- Establecer la cookie `access_token`.
- Devolver solo `registration_complete` y
  `requires_phone_verification`.

### 6. Autenticación de solicitudes con cookie

Actualizar `app/api/dependencies.py`, especialmente `get_current_user`, para
leer el JWT desde la cookie `access_token` y validarlo con la misma clave,
algoritmo y expiración actuales.

Si se necesita una migración gradual de clientes, se puede aceptar
temporalmente `Authorization: Bearer` como alternativa, pero debe definirse
una fecha o versión para retirarlo. No devolver el token de la cookie a una
ruta del frontend.

### 7. CORS y CSRF

`app/main.py` ya habilita `allow_credentials=True`. Mantener orígenes explícitos
en `CORS_ORIGINS`; no combinar credenciales con `allow_origins=["*"]`.

Como las cookies se envían automáticamente, CORS por sí solo no es una
protección CSRF. Para las rutas que cambian estado:

- Validar el encabezado `Origin` contra los orígenes permitidos y/o usar un
  token CSRF sincronizado o double-submit.
- No permitir mutaciones mediante `GET`.
- Mantener `SameSite` en el valor más restrictivo compatible con el despliegue.
- Aplicar esta protección también a login/logout si el diseño de sesión lo
  requiere.

## Cambios en el frontend

### Cliente HTTP

Configurar el cliente API para enviar y recibir cookies:

```ts
// Fetch
fetch(url, {
  credentials: "include",
});

// Axios
axios.create({
  baseURL: API_URL,
  withCredentials: true,
});
```

La llamada a `GET /auth/google` también debe incluir credenciales, porque el
backend establece `oauth_state` en esa respuesta antes de navegar a Google.

Eliminar cualquier código que:

- Lea `access_token` de la respuesta JSON o de parámetros URL.
- Guarde el JWT en `localStorage` o `sessionStorage`.
- Construya manualmente el encabezado `Authorization: Bearer`.

### Página `/google-callback`

La página debe:

1. Leer `code` de la URL.
2. Mostrar un estado de carga mientras hace
   `POST /api/v1/auth/google/exchange`, con
   `credentials: "include"` o `withCredentials: true`.
3. Usar los metadatos JSON para decidir si navega a `/` o a
   `/complete-profile`.
4. Quitar inmediatamente el código de la URL, por ejemplo con
   `history.replaceState`, después de leerlo.
5. Mostrar un error visible y permitir reintentar el inicio de sesión si el
   código expiró, se usó previamente o falló la autenticación.

No persistir el código ni el JWT en almacenamiento web. No enviar el código a
analítica ni registrarlo en logs del navegador.

### Perfil y rutas protegidas

Las solicitudes a `/users/me` y a cualquier ruta protegida deben enviar
credenciales. Si el backend devuelve `401`, el frontend debe considerar que no
hay sesión y enviar al usuario al login.

El flujo de `/complete-profile` debe depender de la respuesta funcional del
backend (`registration_complete` / `requires_phone_verification`) o del usuario
obtenido de `/users/me`, no de valores que el cliente pueda modificar en la URL.

## Variables de entorno y dominios

Ejemplo local:

```env
FRONTEND_URL=http://localhost:3000
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/google/callback
CORS_ORIGINS=http://localhost:3000
```

`GOOGLE_REDIRECT_URI` es el callback del backend y debe coincidir exactamente
con la URI autorizada en Google Cloud Console. `FRONTEND_URL` es el destino de
la redirección del backend después de autenticar.

En producción, configurar URLs HTTPS, `Secure=True` para las cookies y los
orígenes concretos del frontend. Probar específicamente el comportamiento de
cookies con los dominios reales, no solo con localhost.

## Pruebas de aceptación

### Backend

- Login y registro correctos establecen `access_token` con `HttpOnly` y no
  incluyen el JWT en el JSON.
- Credenciales inválidas no establecen una cookie.
- El JWT en cookie autentica `GET /api/v1/users/me`.
- Logout elimina la cookie.
- El callback de Google nunca coloca el JWT en la URL.
- Un código OAuth válido puede canjearse una sola vez.
- Un código expirado, inexistente o ya consumido se rechaza.
- Dos canjes concurrentes del mismo código producen como máximo una sesión.
- La cookie OAuth `oauth_state` se valida y se elimina al terminar.
- CORS permite credenciales solo desde los orígenes configurados.
- Las solicitudes de mutación sin protección CSRF válida se rechazan.

### Frontend

- Login/registro envían credenciales y navegan según los metadatos recibidos.
- El botón de Google inicia navegación a la `authorization_url`.
- `/google-callback` canjea el código, no recibe ni guarda el JWT.
- La URL queda limpia después del canje.
- La página de perfil y las rutas protegidas funcionan con cookies.
- Una sesión vencida o ausente lleva al login y no deja una interfaz en estado
  de carga permanente.

## Archivos a revisar

Backend:

- `app/api/routes/auth.py`
- `app/api/dependencies.py`
- `app/core/config.py`
- `app/main.py`
- `app/schemas/auth.py`
- `app/models/` (nuevo modelo para códigos temporales)
- `migrations/versions/` (nueva migración)
- `tests/` (pruebas de auth y canje)

Frontend:

- Cliente API (`api.ts` o equivalente)
- API de autenticación (`auth-api.ts` o equivalente)
- Formularios de login y registro
- Página `/google-callback`
- Página `/complete-profile`
- Guardas de rutas y manejo de sesión

