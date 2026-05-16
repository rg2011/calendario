# Skill Alexa

La aplicación debe implementar un skill de alexa que permita interactuar con el calendario.

## Alcance

El skill será:

- de tipo `Custom Skill`
- privado, para uso del propietario y opcionalmente sus hermanos
- sin publicación en la store
- sin autenticación de usuario
- solo de lectura
- configurable por código, sin depender de la consola web para cambios funcionales habituales

El skill consultará la misma fuente de datos que usa la aplicación actual y responderá por voz. No permitirá modificar turnos, notas ni ausencias.

## Supuestos operativos

- La aplicación ya dispone de un dominio público con `HTTPS` válido.
- El endpoint del skill podrá servirse bajo una ruta secreta, igual que el resto de la app.
- El mecanismo principal de protección será:
  - firma y validación de peticiones de Alexa
  - prefijo secreto en la URL
- No se requiere `account linking`.
- No se requieren tokens OAuth ni registro de usuarios.

## Dependencias externas

### Amazon / Alexa

- Cuenta en Alexa Developer Console.
- Acceso a SMAPI para gestionar el skill por API.
- `Login with Amazon` configurado para obtener tokens de SMAPI.

### Credenciales para automatización

La automatización del skill requerirá credenciales para SMAPI. La primera versión asumirá este modelo:

- un perfil de seguridad `Login with Amazon`
- `client_id`
- `client_secret`
- `refresh_token` emitido para ese mismo `Security Profile`, para obtener `access_token`

El `refresh_token` no lo generará la herramienta del repositorio. Se obtendrá previamente con `ASK CLI` usando el `client_id` y `client_secret` del `Security Profile` elegido.

Estas credenciales servirán para que una herramienta local pueda crear o actualizar:

- manifest del skill
- interaction model
- endpoint HTTPS
- build del modelo
- validaciones y pruebas
- beta testing, si se usa

Para endpoints HTTPS con certificado publico valido, el manifest debe publicar explicitamente:

- `sslCertificateType: "Trusted"`

## Bootstrap de credenciales SMAPI

El flujo esperado para obtener el `refresh_token` es:

- crear o revisar un `Security Profile` de `Login with Amazon`
- añadir en `Allowed Return URLs`:
  - `http://127.0.0.1:9090/cb`
  - `https://ask-cli-static-content.s3-us-west-2.amazonaws.com/html/ask-cli-no-browser.html`
- ejecutar `ASK CLI` para generar tokens con ese `client_id` y `client_secret`
- guardar en `.env` el `refresh_token` resultante

La herramienta `tools/alexa_sync.py` asume que ese paso ya se ha completado y no implementa la emisión del `refresh_token`.

Scopes recomendados para este proyecto:

- `alexa::ask:skills:read`
- `alexa::ask:skills:readwrite`
- `alexa::ask:models:read`
- `alexa::ask:models:readwrite`
- `alexa::ask:skills:test`

Comando recomendado:

```bash
ask util generate-lwa-tokens \
  --no-browser \
  --client-id <CLIENT_ID> \
  --client-confirmation <CLIENT_SECRET> \
  --scopes "alexa::ask:skills:read alexa::ask:skills:readwrite alexa::ask:models:read alexa::ask:models:readwrite alexa::ask:skills:test"
```

Importante:

- `--scopes` debe pasarse como una sola cadena entre comillas, con los scopes separados por espacios
- si se pasan como argumentos separados, ASK CLI puede no consentir correctamente todos los permisos

### Verificación de identidad

Amazon puede pedir verificación de identidad del titular de la cuenta de desarrollador. Para este proyecto no se prevé publicación en la store, pero si la consola bloquea funciones de envío, distribución o beta, habrá que completar esa verificación.

El objetivo del calendario es gestionar los turnos para atender a los padres. Todas las preguntas están relacionadas con la persona a la que le toca atender a los padres en una cierta fecha, o las notas que se han dejado para esa fecha. El tipo de preguntas que vamos a soportar son:

- ¿A quien le toca <fecha>?
- ¿Quien viene <fecha>?
- ¿Quien va con los padres <fecha>?

En todos los casos, se refiere a lo mismo: quien va a estar rpesencialmente cuidando de los padres en esa fecha. En algunos casos, se pueden dejar notas para esa fecha, y el skill también debe ser capaz de responder a preguntas como:

- ¿Que notas hay para <fecha>?
- ¿Que hay para <fecha>?
- Leeme las notas de <fecha>

## Backend

El backend del skill se integrará en esta misma aplicación Flask.

Se implementarán al menos estas piezas:

- una ruta `POST` para recibir peticiones de Alexa
- una capa de resolución de fecha en español
- una capa de consulta de turno y notas reutilizando la lógica de negocio actual
- respuestas de voz en español

La primera versión evitará dependencias innecesarias y no añadirá persistencia específica para Alexa.

## Configuración del skill por API

El desarrollo del skill debe ir acompañado de una herramienta de automatización que configure el skill sin depender de la interfaz web de Alexa.

La herramienta deberá usar SMAPI para gestionar el skill como configuración versionada dentro del repositorio.

Como mínimo, la herramienta deberá permitir:

- crear el skill si aún no existe
- guardar y reutilizar el `skill_id`
- subir el manifest
- subir el interaction model para `es-ES`
- actualizar el endpoint HTTPS
- lanzar `build` del modelo
- consultar estado del build
- ejecutar validaciones básicas

La consola web quedará como mecanismo secundario de inspección, no como fuente principal de configuración.

## Formatos de fecha

### Abreviaturas

- hoy
- mañana
- pasado
- pasado mañana
- ayer
- anteayer

### Días de la semana

- el lunes, el martes, etc

### Días del mes

- El 15, el 16, etc
- El <día> de <mes>

### Fechas relativas

- dentro de 3 días

### Fechas compuestas

dias de la semana con referencia temporal:

- el martes de la semana que viene
- el miércoles de dentro de dos semanas
- el martes de la semana del 12
- el jueves de la semana del 15 de mayo

Días del mes con referencia temporal:

- el día 15 del mes que viene
- el día 15 del próximo mes

## Intents

## Primera iteración

La primera iteración implementará solo:

- `QueryShiftIntent`
- consulta de la persona asignada a una fecha

El soporte inicial de fecha será deliberadamente limitado a un subconjunto simple de `AMAZON.DATE`:

- `hoy`
- fechas concretas completas
- fechas de mes y día que Alexa pueda resolver sin referencia semanal compleja

Quedan fuera en esta iteración:

- `QueryNotesIntent`
- días de la semana
- semanas relativas
- expresiones complejas como `el martes de la semana que viene`

### Consulta de turno

- A quien le toca <fecha>?
- Quien viene <fecha>?
- Quien va con los padres <fecha>?

### Consulta de notas

- Leeme las notas de <fecha>
- Que hay para <fecha>?
- Que toca <fecha>?
- Qué hay apuntado para <fecha>?
- Que notas hay para <fecha>?

## Modelo de interacción mínimo

### Intents personalizados

- `QueryShiftIntent`
- `QueryNotesIntent`

### Intents estándar

- `AMAZON.HelpIntent`
- `AMAZON.CancelIntent`
- `AMAZON.StopIntent`
- `AMAZON.FallbackIntent`

### Respuesta esperada

Las respuestas deben:

- resolver la fecha hablada a una fecha concreta
- mencionar explícitamente la fecha resuelta
- indicar la persona asignada, o que no hay asignación
- leer la nota si existe

## Artefactos versionados esperados

La configuración del skill debe vivir en ficheros dentro del repositorio. Como mínimo:

- manifest del skill en JSON
- interaction model `es-ES` en JSON
- fichero local de configuración de despliegue
- herramienta o script para sincronizar esos artefactos con SMAPI

## Restricciones de seguridad

El skill se considera de bajo riesgo, pero debe cumplir al menos estas reglas:

- no exponer el endpoint fuera del prefijo secreto
- validar las peticiones entrantes de Alexa
- no aceptar operaciones de escritura
- registrar en logs la fecha resuelta y el intent invocado
