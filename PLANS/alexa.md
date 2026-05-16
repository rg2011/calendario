# Plan De Implementación Del Skill Alexa

## Objetivo

Implementar un skill privado de Alexa para consultar por voz turnos y notas del calendario existente.

Queda fuera de alcance:

- publicación en la Alexa Skills Store
- autenticación por usuario
- edición de datos desde Alexa
- integración con OAuth o `account linking`

## Decisiones ya tomadas

- El skill será `Custom Skill`.
- El backend vivirá en esta misma aplicación Flask.
- El endpoint se publicará en un dominio ya existente con `HTTPS` válido.
- El endpoint usará una ruta secreta.
- El skill será privado y, si hace falta compartirlo, se hará por `beta testing`.
- La configuración del skill no se mantendrá manualmente en la consola web.
- Se desarrollará una herramienta local para gestionar el skill por API mediante SMAPI.

## Lo Que Debes Tener De Amazon

### Ya disponible

- Cuenta en Alexa Developer Console.

### A configurar en la consola

- Solo el bootstrap mínimo si hace falta:
  - crear o revisar credenciales de `Login with Amazon`
  - autorizar el acceso a SMAPI

### Credenciales adicionales necesarias

- `LWA client_id`
- `LWA client_secret`
- `LWA refresh_token`

Estas credenciales son necesarias para que la herramienta local pueda pedir `access_token` y llamar a SMAPI.

El `refresh_token` se obtendrá con `ASK CLI` usando el `Security Profile` elegido. La herramienta del repositorio no generará ese token; solo lo consumirá.

### Lo ideal

- evitar crear o mantener intents, samples, slots y endpoint manualmente en la web
- versionar todo eso en el repo y sincronizarlo por API

### Puede hacer falta

- Verificación de identidad del titular de la cuenta.

Nota:
La documentación actual de Amazon indica que la verificación de identidad puede ser obligatoria cuando Amazon la solicita y que puede restringir funciones de envío o nuevas submissions si no se completa. Como este skill no va a publicarse, no lo tomo como bloqueo inicial de desarrollo, pero sí como posible bloqueo operativo si la consola no deja avanzar con pruebas distribuidas o beta.

## Arquitectura Propuesta

### Opción elegida

Integrar Alexa dentro de la app Flask actual.

Rutas previstas:

- `POST /<secret>/alexa`
- `GET /<secret>/api/alexa/day?date=YYYY-MM-DD`

Además, añadir una capa de automatización del skill, separada del backend de voz.

Artefactos previstos:

- `alexa/skill-package/manifest.json`
- `alexa/interaction-model/es-ES.json`
- `tools/alexa_sync.py` o equivalente
- fichero local con `skill_id` y parámetros de despliegue

Regla operativa del endpoint:

- cuando el backend usa HTTPS con certificado publico valido, la herramienta debe publicar `sslCertificateType: "Trusted"` en el manifest
- no se debe depender de marcar esa opcion manualmente en la consola web

### Motivos

- Reutiliza la lógica ya existente de `app.py`.
- Evita duplicar acceso a SQLite.
- Evita montar un microservicio separado.
- Mantiene bajo el coste operativo.

## Reutilización Del Código Actual

La app ya aporta casi toda la lógica de negocio:

- cálculo del turno por defecto
- sobrescrituras por fecha
- notas por fecha
- ausencias

Puntos del código actual a reutilizar:

- `get_default_shift_for_day(...)`
- `get_shift_for_day(...)`
- modelos `CustomShift`, `DayWeekRule` y `Absence`

## Fases De Implementación

### Slice 1. Intent mínimo de turno

Objetivo:
Cerrar un primer flujo vertical completo para consultar quién tiene el turno en una fecha simple.

Incluye:

- endpoint Alexa funcional
- `QueryShiftIntent`
- slot `AMAZON.DATE`
- soporte inicial para `hoy` y fechas concretas simples
- respuesta de voz con la persona asignada o ausencia de asignación

Queda diferido:

- notas
- parsing libre de fecha
- expresiones semanales complejas

### Fase 1. Base de automatización SMAPI

Objetivo:
Gestionar el skill sin depender de la consola web.

Trabajo:

- elegir formato versionado de artefactos Alexa
- crear script o herramienta local para SMAPI
- implementar autenticación con `refresh_token`
- soportar operaciones mínimas:
  - crear skill
  - obtener skill
  - actualizar manifest
  - actualizar interaction model
  - actualizar endpoint
  - lanzar build
  - consultar estado de build

Decisión de implementación:

- hacerlo en Python para mantener una sola pila técnica
- llamar directamente a SMAPI por HTTP
- no depender de ASK CLI en tiempo de ejecución de la herramienta
- usar ASK CLI solo como bootstrap externo para emitir el `refresh_token` del `Security Profile`

Resultado esperado:

- el skill queda definido por ficheros JSON y un comando reproducible
- el `skill_id` queda persistido localmente

### Fase 2. Capa de consulta interna

Objetivo:
Crear una interfaz interna estable para que Alexa consulte una fecha concreta.

Trabajo:

- extraer o encapsular la lógica de consulta por fecha
- devolver:
  - fecha
  - persona efectiva
  - si la asignación es custom
  - nota
  - persona por defecto

Resultado esperado:

- una función de dominio reutilizable por web y por Alexa
- opcionalmente un endpoint JSON de apoyo para depuración

### Fase 3. Resolución de fechas en español

Objetivo:
Convertir expresiones habladas a una fecha concreta.

Trabajo:

- soportar:
  - hoy
  - mañana
  - pasado mañana
  - ayer
  - anteayer
  - lunes, martes, etc
  - día 15
  - 15 de mayo
  - dentro de 3 días
  - martes de la semana que viene
  - miércoles de dentro de dos semanas
- normalizar la fecha final a `YYYY-MM-DD`

Decisión:

- usar `AMAZON.DATE` cuando ayude
- completar con parsing propio para frases no cubiertas por ese slot

### Fase 4. Endpoint Alexa

Objetivo:
Recibir requests de Alexa y devolver respuestas de voz.

Trabajo:

- añadir ruta `POST /<secret>/alexa`
- validar firma y timestamp de Alexa
- implementar intents:
  - `QueryShiftIntent`
  - `QueryNotesIntent`
  - `AMAZON.HelpIntent`
  - `AMAZON.CancelIntent`
  - `AMAZON.StopIntent`
  - `AMAZON.FallbackIntent`

Respuesta de voz:

- siempre incluir la fecha resuelta
- si no hay turno:
  - decirlo explícitamente
- si no hay nota:
  - decirlo explícitamente

### Fase 5. Modelo de interacción versionado

Objetivo:
Mantener la parte de voz como artefacto versionado y desplegarla por SMAPI.

Trabajo:

- definir invocation name
- crear intents
- crear sample utterances
- definir slot de fecha
- construir el interaction model en JSON
- sincronizarlo con SMAPI desde la herramienta local

Ejemplos de utterances:

- `a quien le toca {fecha}`
- `quien viene {fecha}`
- `quien va con los padres {fecha}`
- `que notas hay para {fecha}`
- `que hay para {fecha}`
- `leeme las notas de {fecha}`

### Fase 6. Pruebas end to end

Objetivo:
Verificar que voz, parsing y respuesta funcionan con frases reales.

Casos mínimos:

- preguntas de turno para hoy y mañana
- preguntas de nota para fechas con y sin nota
- fechas relativas
- fechas con día de la semana
- fechas sin asignación
- fechas con ausencias

Además de las pruebas funcionales del backend, la herramienta debe poder:

- lanzar `build` del modelo
- consultar errores de compilación
- opcionalmente invocar simulaciones por API

### Fase 7. Beta privada

Objetivo:
Compartir el skill sin hacerlo público.

Trabajo:

- activar beta testing si hace falta
- añadir los emails de las cuentas Alexa de tus hermanos
- verificar instalación desde el enlace beta

## Riesgos Y Medidas

### Riesgo 1. Parsing ambiguo de fechas

Mitigación:

- responder siempre con la fecha resuelta
- registrar en logs el texto recibido y la fecha interpretada

### Riesgo 2. Expresiones no cubiertas por `AMAZON.DATE`

Mitigación:

- usar parsing propio como fallback
- empezar por el subconjunto definido en la spec

### Riesgo 3. Restricción operativa por verificación de identidad

Mitigación:

- desarrollar primero el backend y probar en entorno local o con endpoint HTTPS
- completar la verificación solo si la consola bloquea pruebas distribuidas, beta o configuración relevante

### Riesgo 4. Complejidad de autenticación SMAPI

Mitigación:

- hacer un bootstrap manual único para obtener `client_id`, `client_secret` y `refresh_token`
- guardar esas credenciales en variables de entorno o fichero local no versionado
- automatizar a partir de ahí todas las operaciones de skill

### Riesgo 5. Exposición del endpoint

Mitigación:

- mantener el prefijo secreto
- validar peticiones firmadas de Alexa
- no exponer operaciones de escritura

## Checklist Operativo

### Antes de implementar

- confirmar el dominio público final del endpoint
- elegir invocation name
- decidir si habrá beta con tus hermanos desde la primera versión
- obtener `client_id`, `client_secret` y `refresh_token` de SMAPI

### Durante la implementación

- crear o importar skill `Custom` en `es-ES` desde la herramienta
- versionar manifest e interaction model
- configurar endpoint HTTPS por API
- implementar handler Alexa
- construir el interaction model
- lanzar build por API
- probar desde la consola Alexa o por APIs de test cuando convenga

### Antes de compartir

- comprobar respuestas para todos los formatos de fecha de la spec
- revisar logs
- activar beta test si procede

## Diseño De La Herramienta

### Objetivo

Tener un único comando reproducible para sincronizar el skill declarado en el repo con Amazon.

### Comandos mínimos previstos

- `init`
  - crea skill si no existe y guarda `skill_id`
- `push-manifest`
- `push-model`
- `set-endpoint`
- `build-model`
- `status`
- `sync`
  - ejecuta manifest, model, endpoint y build

### Configuración local prevista

Variables de entorno:

- `ALEXA_LWA_CLIENT_ID`
- `ALEXA_LWA_CLIENT_SECRET`
- `ALEXA_LWA_REFRESH_TOKEN`
- `ALEXA_LWA_REDIRECT_URI`
- `ALEXA_LWA_SCOPES`
- `ALEXA_SKILL_ID`
- `ALEXA_SKILL_STAGE`
- `ALEXA_ENDPOINT_URL`

### Bootstrap de credenciales SMAPI

El `refresh_token` debe pertenecer al mismo cliente OAuth que `ALEXA_LWA_CLIENT_ID` y `ALEXA_LWA_CLIENT_SECRET`.

No es valido reutilizar un `refresh_token` emitido para otro cliente.

Procedimiento esperado:

1. En el `Security Profile`, añadir estas `Allowed Return URLs`:
   - `http://127.0.0.1:9090/cb`
   - `https://ask-cli-static-content.s3-us-west-2.amazonaws.com/html/ask-cli-no-browser.html`
2. Ejecutar ASK CLI con el `client_id` y `client_secret` del `Security Profile`.
3. Autorizar con la cuenta developer correcta.
4. Copiar el `refresh_token` emitido para ese cliente.
5. Guardarlo en `.env` como `ALEXA_LWA_REFRESH_TOKEN`.

Scopes baseline recomendados para esta herramienta:

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

Nota operativa:

- `--scopes` debe ir en una sola cadena entre comillas
- con esa sintaxis ya se ha validado en este proyecto que `auth-test` y `push-model` funcionan

### Resultado esperado

Con un solo comando local se debe poder reconstruir la configuración principal del skill sobre la cuenta del desarrollador.

## Criterios De Aceptación

- Alexa responde correctamente quién tiene el turno para una fecha soportada.
- Alexa responde correctamente qué nota hay para una fecha soportada.
- Las respuestas mencionan la fecha interpretada.
- El skill funciona sin autenticación.
- El skill no permite escritura.
- El endpoint queda protegido por HTTPS, prefijo secreto y validación de firma de Alexa.
- El interaction model y el manifest están versionados en el repo.
- La configuración principal del skill puede aplicarse por SMAPI sin editar manualmente la consola web.
