# Plan De Refactorización Modular De La Aplicación

## Objetivo

Reducir la complejidad de `app.py` separando responsabilidades en módulos pequeños y explícitos, sin romper el comportamiento actual ni cambiar la arquitectura funcional de la aplicación.

El objetivo principal del refactor no es habilitar múltiples implementaciones de servicios, sino:

- aislar responsabilidades
- reducir el tamaño de contexto que un agente o desarrollador necesita cargar
- dejar APIs públicas cortas y claras
- mantener la lógica de negocio accesible donde realmente merece la pena leer la implementación
- preparar la app para cambios futuros sin seguir creciendo dentro de `app.py`

## Criterio De Modularización

### Regla principal

Solo usaremos el patrón `Protocol` + constructor `New()` en módulos donde se cumplan estas dos condiciones:

- la API pública tiene pocos métodos
- la implementación concreta es larga, ruidosa o con mucho detalle incidental

En esos casos, el beneficio real es que para entender la API del módulo baste con abrir el `__init__.py`, sin necesidad de cargar también la implementación.

### Casos donde no usar `Protocol`

No usaremos `Protocol` cuando:

- la implementación sea corta o razonablemente legible
- la lógica sea el núcleo del dominio y normalmente haya que leerla para entender el comportamiento
- el ahorro de contexto sea pequeño
- el módulo no exponga una frontera clara entre interfaz pública e implementación interna

## Estado Actual

`app.py` mezcla varias responsabilidades distintas:

- arranque y configuración Flask
- inicialización de SQLAlchemy
- caché HTTP condicional con ETag y Last-Modified
- lógica de turnos
- lógica de ausencias
- render del calendario mensual
- integración con API externa de festivos
- refresco en background de festivos
- integración con Alexa
- serialización JSON
- endpoints HTML
- endpoints API
- migraciones de esquema inline
- hooks de arranque por request

Esto hace que:

- cualquier cambio exija cargar demasiado contexto
- los imports y dependencias implícitas sean difíciles de seguir
- el archivo tenga demasiada responsabilidad operacional
- el coste de revisar o refactorizar una parte concreta sea alto

## Resultado Objetivo

El resultado final buscado es dejar `app.py` como entrypoint fino y mover el resto a `src/`.

Estructura objetivo aproximada:

```text
src/
  app/
    __init__.py
    config.py
    factory.py

  httpcache/
    __init__.py
    cache.py

  holidays/
    __init__.py
    holidays.py

  alexa/
    __init__.py
    alexa.py

  absences/
    __init__.py
    service.py
    serializers.py

  shifts/
    __init__.py
    service.py
    serializers.py

  calendar/
    __init__.py
    service.py
    constants.py

  bootstrap/
    __init__.py
    schema.py
    startup.py

  web/
    __init__.py
    routes_calendar.py
    routes_settings.py
    routes_absences.py
    routes_alexa.py
    routes_static.py

  models/
    __init__.py
    models.py
```

La estructura exacta puede ajustarse durante la ejecución del refactor, pero esta es la dirección.

## Principios Operativos Del Refactor

### 1. Refactor incremental

Cada fase debe dejar la aplicación arrancando y con comportamiento equivalente al anterior.

### 2. Cambios pequeños

No haremos una reescritura masiva en un solo paso. Cada fase moverá una responsabilidad concreta.

### 3. Primero extraer, luego limpiar

Primero moveremos código casi sin cambiar comportamiento. Después reduciremos acoplamientos, renombraremos o afinaremos APIs si hace falta.

### 4. Mantener el dominio reconocible

La lógica central de turnos y ausencias seguirá en implementaciones directas, no escondida detrás de abstracciones innecesarias.

### 5. Minimizar dependencias cruzadas

Las rutas Flask deben depender de servicios de dominio, no al revés.

### 6. Evitar que Flask contamine todo

Siempre que sea razonable:

- `request`, `jsonify`, `render_template`, `url_for` y decoradores de ruta deben quedarse en `web/`
- la lógica de dominio debe vivir fuera de Flask

### 7. Documentación ligera en `__init__.py`

Los `__init__.py` creados durante el refactor deben ayudar a entender la API pública del módulo sin introducir redundancia innecesaria.

Reglas:

- mantener type hints completos en la API pública exportada
- documentar el contrato público con comentarios normales breves cuando aporte contexto
- evitar wrappers solo para añadir docstrings a símbolos ya documentados en la implementación
- usar docstrings en `Protocol`, constructores públicos y funciones exportadas solo cuando añadan información real, no para repetir lo obvio
- preferir reexportación directa si el símbolo ya está bien nombrado y su detalle puede consultarse por LSP o en la implementación

## Qué Módulos Sí Deben Usar `Protocol`

### `src/httpcache/`

Razón:

- API pública pequeña
- implementación técnica relativamente larga
- el consumidor suele necesitar solo `cached_view(...)` y operaciones de versionado

API pública objetivo:

- `New() -> CacheState`
- `cached_view(...)`
- `touch_data()`
- `touch_holidays()`
- `touch(...)`

Implementación concreta:

- cálculo de ETag
- gestión de `Last-Modified`
- soporte a `If-None-Match` y `If-Modified-Since`
- snapshot del día actual

### `src/holidays/`

Razón:

- API pública pequeña
- implementación larga con detalles de red, parseo, locks, caché y threading

API pública objetivo:

- `New(...) -> HolidayProvider`
- `get_month_holidays(year, month)`
- `get_holidays_for_dates(dates)`
- `ensure_refresh_worker()`
- opcionalmente `refresh_holiday_cache_for_year(year)`

Implementación concreta:

- consulta HTTP a la API externa
- parseo tolerante del payload
- almacenamiento en caché anual y mensual
- worker en background
- reintentos con backoff

### `src/alexa/`

Razón:

- API pública muy pequeña
- implementación interna extensa y con mucho detalle incidental

API pública objetivo:

- `New(...) -> AlexaHandler`
- `handle_request(payload)`
- `verify_skill_id(payload)`

Implementación concreta:

- resolución parcial de `AMAZON.DATE`
- formateo de fechas para voz
- normalización de utterances
- fallback conversacional
- dispatch de intents

## Qué Módulos No Deben Usar `Protocol`

### `src/shifts/`

La lógica de turnos es núcleo del dominio. La implementación no es tan grande como para justificar una interfaz artificial, y normalmente sí interesa leer el algoritmo.

### `src/absences/`

La lógica es relativamente simple y de dominio puro. El ahorro de contexto con `Protocol` sería pequeño.

### `src/calendar/`

Aquí interesa leer directamente cómo se monta el mes, el contexto y las semanas visibles.

### `src/bootstrap/`

Son utilidades operacionales de arranque y migración, no una frontera de servicio que compense abstraer.

### `src/models/`

Los modelos SQLAlchemy ya definen suficientemente la forma del dominio persistido.

## Plan De Ejecución

## Fase 1. Extraer Caché HTTP A `src/httpcache/`

### Objetivo

Sacar de `app.py` la clase `AppState` y los helpers de claves de caché.

### Código a mover

- `AppState`
- `calendar_cache_key(...)`
- `current_month_cache_key()`
- `settings_cache_key()`
- `absences_cache_key()`

### Resultado esperado

`app.py` deja de contener la implementación de caché HTTP y pasa a consumirla como dependencia.

### API sugerida

Archivo `src/httpcache/__init__.py`:

- `class CacheState(Protocol): ...`
- `def New() -> CacheState: ...`
- export opcional de helpers de claves

Archivo `src/httpcache/cache.py`:

- implementación concreta de `CacheState`

### Riesgos

- romper los decoradores `@app_state.cached_view(...)`
- perder comportamiento correcto de `304 Not Modified`

### Verificación mínima

- la app arranca
- `/.../` y `/.../calendar/<year>/<month>` responden
- no hay errores al aplicar los decoradores

## Fase 2. Extraer Festivos A `src/holidays/`

### Objetivo

Aislar toda la integración con la API de festivos y su caché en memoria.

### Código a mover

- `extract_holiday_rows(...)`
- `parse_holiday_date(...)`
- `extract_holiday_name(...)`
- `fetch_holidays_from_api(...)`
- `build_month_holiday_cache(...)`
- `get_year_cache_key(...)`
- `get_month_cache_key(...)`
- `get_cached_year_holidays(...)`
- `update_holiday_cache(...)`
- `refresh_holiday_cache_for_year(...)`
- `holiday_refresh_worker()`
- `ensure_holiday_refresh_worker()`
- `get_month_holidays(...)`
- `get_holidays_for_dates(...)`

### Dependencias a inyectar o resolver

- `app.logger`
- `app_state.touch_holidays()`
- configuración de API y timeouts

### Decisión importante

El módulo no debe depender de `app.py`. Debe recibir o construir explícitamente lo necesario.

Opciones razonables:

- pasar `logger` y `cache_state` al constructor
- encapsular configuración en una clase simple o parámetros del constructor

### Resultado esperado

Las rutas y el calendario consumen un servicio de festivos ya inicializado, sin conocer detalles de locks, cache keys o threads.

### Riesgos

- acoplar accidentalmente `holidays.py` a Flask
- romper el worker de refresco
- perder la actualización de `touch_holidays()`

### Verificación mínima

- la app arranca
- el worker de festivos se inicia
- el calendario sigue renderizando aunque no haya datos en caché
- si la API falla, no se rompe la request

## Fase 3. Extraer Ausencias A `src/absences/`

### Objetivo

Sacar de `app.py` la lógica de lectura y escritura de ausencias.

### Código a mover

- `serialize_absence(...)`
- `get_absences_for_dates(...)`
- `is_person_absent_on_date(...)`
- parte de `manage_absences()` que implementa CRUD

### Estructura sugerida

`src/absences/service.py`

- consultas por rango
- comprobación de ausencia por persona y fecha
- upsert y delete

`src/absences/serializers.py`

- serialización JSON

### Resultado esperado

Las rutas Flask dejan de manipular el ORM directamente salvo quizá para adaptadores muy finos.

### Riesgos

- romper la edición de ausencias existentes
- romper el caso especial de edición que cambia clave primaria compuesta

### Verificación mínima

- `GET /api/absences`
- alta de ausencia
- edición de ausencia
- borrado de ausencia

## Fase 4. Extraer Turnos A `src/shifts/`

### Objetivo

Concentrar la lógica de reglas semanales, custom shifts y resúmenes diarios.

### Código a mover

- `get_week_start(...)`
- `get_default_shift_for_day(...)`
- `get_shift_for_day(...)`
- `get_shift_summary_for_date(...)`
- `serialize_rule(...)`
- parte de `manage_rules()`
- parte de `set_custom_shift()`

### Estructura sugerida

`src/shifts/service.py`

- cálculo de turnos por defecto
- resolución del turno efectivo
- resumen diario
- actualización de custom shifts
- actualización de reglas

`src/shifts/serializers.py`

- serialización de reglas

### Resultado esperado

El dominio de turnos queda autocontenido y se convierte en dependencia explícita del calendario y de Alexa.

### Dependencia funcional importante

Alexa no debe recalcular turnos ni consultar ausencias por su cuenta.

La relación correcta es esta:

- `absences/` resuelve ausencias
- `shifts/` resuelve el turno efectivo usando reglas, custom shifts y ausencias
- `calendar/` y `alexa/` consumen esa resolución

Eso implica que, antes de extraer Alexa, debe existir ya en `src/shifts/` una API suficientemente estable para algo como:

- `get_shift_summary_for_date(...)`
- `get_shift_summary_for_target(...)` o equivalente

De ese modo, Alexa depende de `shifts/`, no directamente de `absences/`.

### Riesgos

- romper la interacción entre turnos y ausencias
- cambiar comportamiento de la rotación semanal
- introducir dependencias circulares con `absences/`

### Mitigación

Mantener la dependencia en una sola dirección:

- `shifts/` puede usar `absences/`
- `absences/` no debe usar `shifts/`

### Verificación mínima

- `GET/POST /api/rules`
- `POST /api/custom-shift`
- turnos por defecto correctos
- un custom shift con persona ausente sigue validando como antes

## Fase 5. Extraer Calendario A `src/calendar/`

### Objetivo

Sacar la construcción del calendario mensual y el contexto para plantilla.

### Código a mover

- `MONTH_NAMES_ES`
- `get_previous_month(...)`
- `get_next_month(...)`
- `month_date_range(...)`
- `get_month_days_full(...)`
- `render_calendar(...)`

### Observación

`month_date_range(...)` está hoy junto a festivos, pero conceptualmente es utilidad de calendario. Puede ir aquí si no complica dependencias.

### Diseño sugerido

`src/calendar/service.py`

- construir días visibles
- agrupar semanas
- enriquecer días con turnos, ausencias y festivos
- devolver contexto para plantilla

`src/calendar/constants.py`

- nombres de meses
- días de la semana abreviados

### Resultado esperado

La ruta HTML del calendario delega la construcción del contexto a este módulo.

### Riesgos

- acoplar demasiado el módulo a `url_for`
- mezclar lógica de dominio con detalles de navegación HTML

### Mitigación

Separar en lo posible:

- una función que construye el modelo del mes
- otra que completa el contexto web

### Verificación mínima

- vista principal `/.../`
- vista mensual `/.../calendar/<year>/<month>`
- navegación anterior/siguiente
- render correcto de festivos, ausencias y sobrescrituras

## Fase 6. Extraer Alexa A `src/alexa/`

### Objetivo

Separar toda la lógica Alexa del resto de la aplicación una vez que la resolución de turnos ya vive en `src/shifts/`.

### Código a mover

- `LOCAL_TZ`
- `resolve_simple_alexa_date(...)`
- `format_date_for_speech(...)`
- `format_weekend_for_speech(...)`
- `_join_people_for_speech(...)`
- `get_shift_summary_for_target(...)` si se decide que es una adaptación específica de Alexa
- `_format_enumerated_notes_for_speech(...)`
- `alexa_plain_text_response(...)`
- `verify_alexa_skill_id(...)`
- helpers conversacionales y de transcript
- `handle_query_shift_intent(...)`
- `handle_query_notes_intent(...)`
- `handle_alexa_request(...)`

### Dependencias a resolver

- `ALEXA_SKILL_ID`
- servicio de turnos ya extraído

### Diseño sugerido

`src/alexa/__init__.py` debe exponer algo parecido a:

- `class AlexaHandler(Protocol): ...`
- `def New(skill_id: str, shift_service: ...) -> AlexaHandler`

### Regla de dependencia

Alexa debe depender de una API de `shifts/` que ya resuelva el turno efectivo teniendo en cuenta:

- reglas semanales
- custom shifts
- ausencias

Alexa no debe depender directamente de `absences/`, porque no necesita conocer ese detalle de implementación.

### Resultado esperado

La ruta Flask de Alexa se limita a:

- leer payload
- verificar skill id
- loggear tipo de request e intent
- delegar al handler

### Riesgos

- acoplar Alexa a helpers todavía alojados en `app.py`
- exponer una API de turnos insuficiente y obligar a Alexa a rehacer parte de la lógica

### Mitigación

No extraer Alexa hasta que `src/shifts/` ofrezca ya el resumen que necesita.

### Verificación mínima

- el webhook `/.../alexa` sigue respondiendo
- `LaunchRequest` funciona
- `QueryShiftIntent` y `QueryNotesIntent` siguen construyendo respuesta
- las respuestas de Alexa siguen respetando ausencias porque consumen la misma resolución de turnos que el calendario

## Fase 7. Extraer Bootstrap Y Esquema A `src/bootstrap/`

### Objetivo

Separar del entrypoint la lógica operacional de arranque.

### Código a mover

- `ensure_custom_shift_schema()`
- `ensure_absence_schema()`
- `create_tables()` como hook
- posibles helpers de inicialización

### Estructura sugerida

`src/bootstrap/schema.py`

- funciones de asegurado/migración de tablas

`src/bootstrap/startup.py`

- inicialización de tablas
- ejecución de comprobaciones de esquema
- arranque de workers

### Observación

Estas funciones son una solución transitoria tipo migración inline. No deben crecer indefinidamente. A medio plazo sería mejor sustituirlas por Alembic o migraciones explícitas.

### Resultado esperado

El arranque queda centralizado y el comportamiento operacional es más visible.

### Riesgos

- cambiar el orden de inicialización
- ejecutar workers antes de tiempo

### Verificación mínima

- arranque normal vía `python app.py`
- hook `before_request` sigue inicializando lo necesario
- no hay errores si la base ya existe

## Fase 8. Extraer Rutas Flask A `src/web/`

### Objetivo

Dejar `app.py` o `src/app/factory.py` como composición de blueprints o registro de rutas.

### Código a mover

- `index()`
- `calendar_view()`
- `web_app_manifest()`
- `manage_rules()`
- `set_custom_shift()`
- `manage_absences()`
- `settings()`
- `absences()`
- `secret_static()`
- `alexa_webhook()`

### Estructura sugerida

- `routes_calendar.py`
- `routes_settings.py`
- `routes_absences.py`
- `routes_alexa.py`
- `routes_static.py`

### Decisión de implementación

No es obligatorio introducir blueprints desde el primer momento. Se puede empezar con funciones de registro del tipo:

- `register_calendar_routes(app, ...)`
- `register_alexa_routes(app, ...)`

Si más adelante conviene, se migra a blueprints.

### Resultado esperado

La composición final de la app será mucho más explícita:

- crear app
- inicializar db
- construir servicios
- registrar rutas
- registrar hooks de startup

### Riesgos

- errores por nombres de endpoint usados en `url_for`
- perder acceso a dependencias compartidas como `people`, `app_state` o servicios

### Verificación mínima

- todas las rutas existentes siguen resolviendo
- `url_for(...)` sigue funcionando
- el manifest web sigue apuntando a endpoints válidos

## Fase 9. Reducir `app.py` A EntryPoint Fino

### Objetivo

Dejar el archivo principal con solo la composición de alto nivel.

### Contenido objetivo de `app.py`

- cargar `.env`
- obtener configuración básica
- crear app Flask
- inicializar `db`
- construir servicios
- registrar rutas
- registrar startup
- ejecutar `app.run(...)` si procede

### Resultado esperado

`app.py` deja de ser un archivo de lógica y pasa a ser un archivo de ensamblado.

## Dependencias Entre Fases

Orden recomendado:

1. `httpcache`
2. `holidays`
3. `absences`
4. `shifts`
5. `calendar`
6. `alexa`
7. `bootstrap`
8. `web`
9. limpieza final de `app.py`

### Motivo del orden

- `httpcache` y `holidays` son buenos candidatos tempranos porque tienen mucha implementación y una API pública razonablemente pequeña
- `absences` y `shifts` deben extraerse antes que `alexa`, porque la resolución efectiva del turno depende de ausencias
- `calendar` depende de turnos, ausencias y festivos
- `alexa` debe apoyarse en la misma API de turnos que usa el calendario, no rehacer su lógica
- `web` conviene dejarlo para el final, cuando las dependencias de dominio ya están estabilizadas

## Reglas Para Cada Paso Del Refactor

En cada fase seguiremos esta secuencia:

1. crear el nuevo módulo y su API pública
2. mover la implementación con los mínimos cambios posibles
3. adaptar imports en `app.py`
4. arrancar verificación mínima
5. solo después, limpiar nombres o reorganizar detalles internos

## Verificación General En Cada Fase

Como mínimo, tras cada fase debería comprobarse:

- la app importa sin error
- la app arranca
- las rutas principales siguen respondiendo
- no aparecen ciclos de importación

Cuando la fase afecte a comportamiento específico, además:

- calendario: render mensual correcto
- ausencias: CRUD correcto
- turnos: reglas y sobrescrituras correctas
- Alexa: intents principales correctos
- festivos: fallback seguro si la API externa falla

## Riesgos Globales Del Refactor

### 1. Dependencias circulares

Riesgo alto entre:

- `calendar`
- `shifts`
- `absences`
- `alexa`

Mitigación:

- `absences` no depende de nadie del dominio
- `shifts` puede depender de `absences`
- `calendar` depende de `shifts`, `absences` y `holidays`
- `alexa` depende de `shifts`

### 2. Riesgo de duplicar la resolución del turno

Riesgo:

- que `calendar` y `alexa` terminen teniendo caminos distintos para decidir la persona efectiva de un día

Mitigación:

- la resolución efectiva del turno debe vivir en `src/shifts/`
- `calendar` y `alexa` deben consumir esa misma API
- `alexa` no debe consultar ausencias ni reglas directamente

### 3. Acoplamiento accidental a Flask

Riesgo:

- mover servicios fuera de `app.py` pero seguir importando `request`, `app`, `url_for` o `render_template` dentro de ellos

Mitigación:

- limitar Flask a `web/`
- pasar dependencias explícitas cuando sea necesario

### 4. Cambios de comportamiento no deseados

Riesgo:

- que el refactor altere reglas de negocio o flujos de edición

Mitigación:

- mover primero sin rediseñar
- verificar después de cada extracción

### 5. Inicialización en orden incorrecto

Riesgo:

- usar servicios antes de inicializar `db`
- arrancar workers sin contexto necesario

Mitigación:

- centralizar composición en el factory o bootstrap

## Mejoras Posibles Que Quedan Fuera De Este Refactor

Estas mejoras son razonables, pero no forman parte del objetivo principal del refactor y no deberían mezclarse salvo necesidad:

- introducir blueprints formales si inicialmente se opta por funciones de registro
- migrar las migraciones inline a Alembic
- introducir tests automáticos específicos por módulo
- extraer configuración a clases más estructuradas
- sustituir algunas funciones por dataclasses de dominio para el modelo del calendario
- desacoplar más el render HTML del armado de datos

## Definición De Éxito

Consideraremos el refactor exitoso cuando:

- `app.py` deje de contener la lógica principal de negocio
- los módulos largos y ruidosos queden detrás de APIs públicas cortas cuando eso aporte ahorro real de contexto
- la lógica central del dominio quede organizada y localizable
- la aplicación mantenga el comportamiento actual
- un agente pueda entender cada subsistema cargando solo el módulo adecuado, sin abrir necesariamente todo `app.py`

## Siguiente Paso Recomendado

Empezar por `src/httpcache/`.

Razones:

- cambio pequeño
- poco riesgo funcional
- patrón `Protocol` útil
- reduce ruido técnico pronto
- prepara el terreno para extraer luego `holidays/` y rutas cacheadas
