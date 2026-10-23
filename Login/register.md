Bien primero necesito que tome de ejemplo el .env.example y generes mi .env, lo segundo que Quiero implementar en mi proyecto backend un sistema completo de autenticación y registro utilizando **Google OAuth 2.0 / OpenID Connect** como método de inicio de sesión, junto con **verificación obligatoria del número de teléfono mediante OTP por SMS**
## Objetivo general
El usuario debe poder iniciar sesión mediante Google.

Sin embargo, **un usuario nuevo NO debe obtener acceso completo a la aplicación inmediatamente después de autenticarse con Google**.

Si el usuario es nuevo, debe completar el registro proporcionando un número de teléfono y verificándolo mediante un código OTP.

Durante esta primera implementación, **NO conectar Twilio todavía**.

Debe implementarse una abstracción/proveedor de SMS con un **OTP simulado para desarrollo**, de manera que posteriormente pueda reemplazarse fácilmente por Twilio Verify Trial sin modificar la lógica principal de autenticación.
Usuario
   |
   | "Continuar con Google"
   v
Google OAuth/OIDC
   |
   v
Backend
   |
   |-- ¿Existe el usuario?
   |
   +---- NO ----> Crear usuario incompleto
   |                  |
   |                  v
   |            Solicitar teléfono
   |                  |
   |                  v
   |             Generar OTP
   |                  |
   |                  v
   |             OTP simulado
   |                  |
   |                  v
   |             Usuario introduce OTP
   |                  |
   |                  v
   |            Verificar OTP
   |                  |
   |                  v
   |            phone_verified = true
   |                  |
   |                  v
   |             Usuario ACTIVE
   |
   +---- SÍ ----> ¿Teléfono verificado?
                         |
                  +------+------+
                  |             |
                 NO            SÍ
                  |             |
                  v             v
           Completar registro  Crear sesión
                                |
                                v
                             Dashboard
La regla principal es:

> Google autentica la identidad del usuario, pero el backend determina si el usuario tiene permitido acceder a las funcionalidades protegidas.
2. Google OAuth / OpenID Connect
Implementar autenticación mediante Google utilizando OAuth 2.0 / OpenID Connect.

No confiar únicamente en información enviada por el frontend.

El backend debe validar correctamente la identidad proporcionada por Google.

Utilizar el identificador estable de Google (sub) como identificador externo de la cuenta.

NO utilizar el email como identificador principal de la cuenta de Google.

Guardar como mínimo:

google_sub
email
name
picture/avatar

El email debe almacenarse como información del usuario, pero google_sub debe utilizarse para identificar la cuenta de Google.
El campo phone_verified debe ser booleano.

El campo status debe representar el estado de registro/autenticación del usuario.

Preferentemente utilizar estados como:

PENDING_PHONE
ACTIVE

Si consideras que una máquina de estados más explícita es mejor, puedes implementar:

GOOGLE_AUTHENTICATED
PHONE_REQUIRED
PHONE_VERIFICATION_PENDING
ACTIVE

pero evita sobrecomplicar el modelo si no es necesario

Usuarios nuevos
Cuando Google autentique correctamente a un usuario:

Si el google_sub NO existe:
Crear un usuario nuevo.

Ejemplo:

google_sub = "123456789"
email = "usuario@gmail.com"
name = "Usuario"
phone_number = NULL
phone_verified = false
status = PENDING_PHONE

No permitirle acceder todavía a endpoints que requieran una cuenta completamente registrada.

El backend debe indicar al frontend que el usuario necesita completar la verificación telefónica.

Por ejemplo:

{
    "authenticated": true,
    "registration_complete": false,
    "requires_phone_verification": true
}

5. Usuarios existentes
Si el usuario ya existe:

Caso A
phone_verified = true
status = ACTIVE

Crear la sesión normalmente y permitir acceso.

Caso B
phone_verified = false

No permitir acceso completo.

El frontend debe ser informado de que el usuario debe completar la verificación telefónica.

6. Verificación telefónica
El usuario nuevo debe llegar a un flujo como:

Completa tu registro

Número de teléfono:
+57 3001234567

[Enviar código]

El frontend enviará el teléfono al backend.

El backend debe:

Validar que el número tenga un formato válido.

Normalizar el número.

Asociarlo al usuario autenticado.

Generar un OTP.

Guardarlo temporalmente de forma segura.

Enviar el OTP utilizando un proveedor de SMS abstracto.

NO implementar Twilio todavía.

7. OTP simulado
Crear una abstracción para el proveedor de SMS.

Por ejemplo:

class SmsProvider:
    async def send_verification_code(
        self,
        phone_number: str,
        code: str
    ) -> None:
        ...

Crear una implementación para desarrollo:

class MockSmsProvider(SmsProvider):
    ...

Esta implementación NO debe enviar ningún SMS real.

Debe imprimir/loguear el código generado, por ejemplo:

========================================
MOCK SMS
To: +573001234567
OTP: 483921
========================================

De esta manera puedo probar todo el flujo localmente.

8. Preparar la arquitectura para Twilio
Aunque inicialmente solo quiero MockSmsProvider, la arquitectura debe permitir posteriormente implementar:

class TwilioSmsProvider(SmsProvider):
    ...

sin modificar:

los endpoints

el servicio de autenticación

el modelo User

el flujo de registro

la lógica de negocio

La selección del proveedor debe hacerse mediante configuración.

Por ejemplo:

SMS_PROVIDER=mock

Posteriormente:

SMS_PROVIDER=twilio

No implementar todavía la integración real con Twilio.

9. OTP
El OTP debe:

Tener 6 dígitos.

Generarse utilizando un mecanismo criptográficamente seguro.

Tener una expiración corta, por ejemplo 5 minutos.

No almacenarse en texto plano si se puede evitar.

Tener un número máximo de intentos.

Invalidarse después de utilizarse correctamente.

No poder reutilizarse.

Permitir solicitar un nuevo código después de un periodo de cooldown.

Ejemplo:

OTP:
483921

Expira:
5 minutos

Máximo de intentos:
5

No devolver el OTP en la respuesta HTTP de la API.

El OTP solamente debe aparecer en logs cuando se esté utilizando MockSmsProvider.

10. Endpoints
Crear una estructura de endpoints similar a:

GET /auth/google
GET /auth/google/callback

GET /auth/me
POST /auth/logout

POST /auth/phone/send-code
POST /auth/phone/verify

Puedes modificar los nombres si la arquitectura existente utiliza otra convención.

GET /auth/google
Inicia el flujo de autenticación con Google.

GET /auth/google/callback
Recibe el callback de Google.

Debe:

Validar la respuesta de Google.

Obtener el sub.

Obtener email/nombre/avatar.

Buscar el usuario.

Crear el usuario si no existe.

Determinar si necesita verificación telefónica.

Crear la sesión correspondiente.

Redirigir o devolver la información necesaria al frontend según la arquitectura actual.

11. Endpoint para enviar OTP
Crear:

POST /auth/phone/send-code

Ejemplo:

{
    "phone_number": "+573001234567"
}

Debe:

Requerir que exista una sesión/autenticación válida de Google.

Obtener el usuario desde la sesión.

Validar el número.

Generar OTP.

Guardarlo de manera segura.

Llamar al SmsProvider.

Responder algo como:

{
    "success": true,
    "message": "Verification code sent"
}

No devolver el OTP.

12. Endpoint para verificar OTP
Crear:

POST /auth/phone/verify

Body:

{
    "phone_number": "+573001234567",
    "code": "483921"
}

Debe:

Obtener al usuario autenticado.

Buscar el OTP correspondiente.

Comprobar que no haya expirado.

Comprobar que no haya superado el número máximo de intentos.

Comparar el código de manera segura.

Invalidar el OTP después de una verificación correcta.

Marcar:

phone_verified = true

Guardar el número normalizado.

Cambiar:

status = ACTIVE

Permitir el acceso completo del usuario.

Respuesta esperada:

{
    "success": true,
    "phone_verified": true,
    "registration_complete": true
}

13. Sesiones
Utilizar una estrategia segura de sesión.

Si el proyecto ya tiene un mecanismo de autenticación/sesión, reutilizarlo en lugar de crear otro sistema innecesariamente.

Si no existe ninguno, implementar una solución adecuada para una aplicación web con frontend separado.

Preferir cookies:

HttpOnly
Secure
SameSite

cuando la arquitectura lo permita.

No guardar credenciales sensibles en localStorage.

El backend debe ser la autoridad para determinar si un usuario puede acceder a recursos protegidos.

14. Protección de endpoints
Crear una dependencia/middleware/helper para obtener el usuario autenticado.

Por ejemplo:

current_user

Además, debe existir una comprobación para usuarios con registro completo.

Conceptualmente:

get_current_user()

comprueba autenticación.

Y:

require_active_user()

comprueba:

authenticated == true
phone_verified == true
status == ACTIVE

Los endpoints privados importantes deben utilizar require_active_user().

Un usuario que solamente haya iniciado sesión con Google pero no haya verificado su teléfono NO debe poder acceder a los recursos protegidos.

15. Seguridad
Aplicar buenas prácticas de seguridad.

Como mínimo:

Validar correctamente OAuth/OIDC.

Validar state en el flujo OAuth cuando corresponda.

No confiar en datos de identidad proporcionados directamente por el frontend.

No aceptar un user_id enviado por el cliente para determinar quién está autenticado.

Usar la sesión para determinar el usuario actual.

No devolver OTP en respuestas HTTP.

No almacenar OTP en texto plano si se puede evitar.

Utilizar expiración.

Limitar intentos.

Implementar cooldown para solicitar nuevos OTP.

Evitar enumeración de usuarios.

Validar y normalizar números telefónicos.

Evitar logs de información sensible en producción.

Utilizar variables de entorno para secretos.

No hardcodear Google Client ID/Secret.

No hardcodear futuros secretos de Twilio.

16. Configuración
Crear/configurar variables de entorno similares a:

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=

DATABASE_URL=

SMS_PROVIDER=mock

OTP_EXPIRATION_SECONDS=300
OTP_MAX_ATTEMPTS=5
OTP_RESEND_COOLDOWN_SECONDS=60

No incluir valores reales en el código.

Preparar la configuración para que posteriormente se pueda agregar:

TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_VERIFY_SERVICE_SID=

pero NO utilizar estas variables todavía.

17. Base de datos para OTP
Crear una tabla separada para los códigos de verificación si es apropiado para la arquitectura existente.

Por ejemplo:

phone_verification_codes

id
user_id
phone_number
code_hash
expires_at
attempts
verified_at
created_at

El código debe quedar invalidado cuando:

verified_at != NULL

o cuando haya expirado.

Crear la migración correspondiente utilizando Alembic.

18. Formato de teléfono
Normalizar el numero de telefono ya que es para colombia +57
19. Manejo de errores
Crear errores claros para casos como:

Invalid phone number
Verification code expired
Invalid verification code
Too many attempts
Too many requests
Verification code already used
Phone already associated with another account
Authentication required
Phone verification required

No revelar información innecesaria que facilite ataques de enumeración.

20. Reglas de negocio importantes
Estas reglas son obligatorias:

Usuario nuevo
Google autenticado
+
Teléfono NO verificado
=
NO acceso completo

Usuario existente con teléfono verificado
Google autenticado
+
phone_verified = true
+
status = ACTIVE
=
ACCESO

Usuario existente sin teléfono verificado
Google autenticado
+
phone_verified = false
=
DEBE COMPLETAR VERIFICACIÓN

OTP correcto
OTP correcto
=
phone_verified = true
+
status = ACTIVE

OTP incorrecto
OTP incorrecto
=
NO activar usuario

21. No hacer todavía
NO implementar todavía:

Twilio

envío de SMS real

Firebase Authentication

recuperación de contraseña mediante SMS

cambio de teléfono

MFA completo

múltiples proveedores OAuth

login mediante email/password

La primera versión debe enfocarse exclusivamente en:

Google OIDC
+
registro de usuario
+
teléfono obligatorio
+
OTP simulado
+
sesión
+
protección de endpoints

22. Compatibilidad futura con Twilio
Quiero que el código quede preparado para cambiar:

MockSmsProvider

por:

TwilioSmsProvider

sin modificar la lógica del flujo.

La lógica debe depender de una interfaz/protocolo:

AuthenticationService
        |
        v
SmsProvider
        |
        +---- MockSmsProvider
        |
        +---- TwilioSmsProvider (futuro)

23. Tests
Crear tests para los casos principales.

Como mínimo:

Usuario nuevo inicia sesión con Google.

Usuario existente inicia sesión con Google.

Usuario nuevo queda en PENDING_PHONE.

Usuario nuevo no puede acceder a endpoints protegidos.

Se puede solicitar OTP.

OTP se genera correctamente.

OTP incorrecto falla.

OTP expirado falla.

OTP supera máximo de intentos.

OTP correcto activa el usuario.

OTP no puede reutilizarse.

Usuario activo puede acceder a endpoints protegidos.

No se puede solicitar OTP sin autenticación.

No se puede utilizar un teléfono asociado a otro usuario si esa es una regla del sistema.

El cooldown de reenvío funciona.

Utilizar mocks para Google y MockSmsProvider en los tests.

No hacer llamadas reales a Google ni a Twilio durante los tests.

24. Entregables
Quiero que implementes la funcionalidad completa dentro de la estructura existente del proyecto.

Antes de modificar archivos:

Analiza la estructura actual.

Identifica cómo está implementada actualmente la autenticación, si existe.

Identifica los modelos existentes de usuario.

Identifica cómo se manejan las sesiones/JWT/cookies.

Identifica cómo se realizan las migraciones.

Reutiliza la arquitectura existente siempre que sea razonable.

Después:

Implementa los modelos necesarios.

Implementa las migraciones.

Implementa Google OAuth/OIDC.

Implementa el flujo de usuarios nuevos.

Implementa SmsProvider.

Implementa MockSmsProvider.

Implementa generación y validación segura de OTP.

Implementa los endpoints.

Implementa la protección de endpoints.

Implementa tests.

Actualiza .env.example.

Documenta cómo ejecutar y probar el flujo localmente.

No quiero una implementación superficial ni código de ejemplo aislado.

Quiero que la funcionalidad quede integrada con la arquitectura existente del backend.

Al finalizar, explícame:

qué archivos modificaste/creaste;

cómo funciona el flujo completo;

cómo configurar Google OAuth localmente;

cómo probar el OTP simulado;

cómo cambiar posteriormente MockSmsProvider por TwilioSmsProvider;

qué comandos ejecutar para migraciones y tests;

y cualquier decisión arquitectónica importante que hayas tomado.