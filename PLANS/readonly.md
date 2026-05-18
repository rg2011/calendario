# Plan De Segunda Ruta Secreta Solo Lectura

## Objetivo

Soportar una segunda ruta secreta compartible en modo solo lectura.

La ruta actual seguirá permitiendo leer y modificar calendario, reglas y ausencias. La nueva ruta permitirá navegar por la misma aplicación, pero no permitirá modificar datos y no expondrá el contenido de las notas de los turnos personalizados.

Queda fuera de alcance:

- autenticación de usuarios
- gestión de permisos por persona
- cambios de esquema en SQLite
- duplicar la aplicación o montar un blueprint separado completo
- rediseñar la plantilla para una experiencia de solo lectura

## Decisiones Ya Tomadas

- Se añadirá una segunda variable de entorno para el secreto de solo lectura.
- Las rutas Flask pasarán a tener un prefijo dinámico `/<secret>/...`.
- Un middleware resolverá si el `secret` recibido es de lectura/escritura o de solo lectura.
- Cualquier `secret` desconocido devolverá `404`.
- La ruta de solo lectura bloqueará métodos de escritura.
- La ruta de solo lectura no mostrará el contenido de `note`.
- No hace falta ocultar `/settings`, `/absences`, `GET /api/rules` ni `GET /api/absences`.
- La ruta `/alexa` no estará disponible desde el secreto de solo lectura.
- La plantilla `calendar.html` puede mantenerse casi igual si recibe el contexto sin notas.

## Configuración

Variables previstas:

```env
CALENDARIO_SECRET_PATH=mi-ruta-escritura
CALENDARIO_READONLY_SECRET_PATH=mi-ruta-lectura
```

Validaciones:

- `CALENDARIO_SECRET_PATH` sigue siendo obligatoria.
- `CALENDARIO_READONLY_SECRET_PATH` será obligatoria para activar este modo.
- Ambos valores deben ser un único segmento de ruta, sin `/`.
- Ambos valores deben ser distintos.

Si se quiere permitir despliegues sin ruta de solo lectura, `CALENDARIO_READONLY_SECRET_PATH` podría ser opcional. En ese caso el middleware solo aceptaría la ruta de escritura. La opción preferida para este cambio es hacerla obligatoria, para evitar que parezca configurada sin estarlo.

## Modelo De Acceso En Request

Crear una capa pequeña en `app.py` o en un módulo posterior, si encaja con el refactor:

```python
READ_WRITE = "read_write"
READ_ONLY = "read_only"
```

El middleware debe:

- extraer el primer segmento de `request.path`
- compararlo con `SECRET_PATH` y `READONLY_SECRET_PATH`
- guardar en `g.secret_path` el secreto actual
- guardar en `g.access_mode` el modo resuelto
- devolver `404` si no coincide con ninguno
- bloquear escrituras si `g.access_mode == READ_ONLY`

Métodos bloqueados en solo lectura:

- `POST`
- `PUT`
- `PATCH`
- `DELETE`

Aunque ahora no haya rutas `PUT` ni `PATCH`, conviene bloquearlas desde el principio para que futuras APIs no queden abiertas por accidente.

## Rutas

Cambiar los decoradores actuales con prefijo fijo:

```python
@app.route(f"/{SECRET_PATH}/calendar/<int:year>/<int:month>")
```

por rutas con prefijo dinámico:

```python
@app.route("/<secret>/calendar/<int:year>/<int:month>")
```

El parámetro `secret` no debe usarse como fuente de confianza dentro de las vistas. La decisión de acceso debe venir del middleware y de `g.access_mode`.

Rutas afectadas:

- `/<secret>/`
- `/<secret>/calendar/<year>/<month>`
- `/<secret>/manifest.webmanifest`
- `/<secret>/api/rules`
- `/<secret>/api/custom-shift`
- `/<secret>/api/absences`
- `/<secret>/settings`
- `/<secret>/absences`
- `/<secret>/static/<path:filename>`
- `/<secret>/alexa`

## `url_for`

Todas las llamadas internas a `url_for` que apunten a rutas bajo el prefijo secreto deben incluir el secreto actual:

```python
url_for("calendar_view", secret=g.secret_path, year=year, month=month)
```

Esto evita que una persona que entra por la ruta de solo lectura sea enviada a enlaces de lectura/escritura.

Lugares a revisar:

- generación de calendario anterior/siguiente
- selector de mes/año en `calendar.html`
- enlaces de navegación en `base.html`
- `manifest.webmanifest`
- iconos y CSS servidos por `secret_static`
- APIs usadas por JavaScript

## Bloqueo De Escritura

El middleware debe bloquear escritura antes de llegar a las vistas. Así no hay que repetir comprobaciones en cada endpoint.

Respuesta recomendada:

- `404` para secretos inválidos
- `403` para método no permitido por modo solo lectura

`403` hace más fácil depurar y deja claro que la ruta existe pero no permite esa acción. Si se prefiere mantener la semántica de "lo no permitido no existe", se puede usar `404` también para escrituras en read-only, pero entonces los errores de UI serán menos explícitos.

Endpoints que quedan bloqueados automáticamente en read-only:

- `POST /<secret>/api/rules`
- `POST /<secret>/api/custom-shift`
- `POST /<secret>/api/absences`
- `DELETE /<secret>/api/absences`
- cualquier futura ruta `PUT` o `PATCH`

## Notas

Las notas viven en `custom_shifts.note` y llegan a la plantilla desde `CalendarService.build_context`.

Cambiar `build_context` para aceptar un parámetro:

```python
include_notes: bool = True
```

En el bucle de días:

```python
day["note"] = note if include_notes else None
```

En las vistas de calendario:

```python
context = calendar_service.build_context(
    year,
    month,
    calendar_url_builder=...,
    include_notes=g.access_mode != READ_ONLY,
)
```

La plantilla actual usa:

```html
data-note="{{ day.note or '' }}"
```

Por tanto, si el contexto llega con `note=None`, el contenido de la nota no se serializa en el HTML.

## Plantillas

No se requiere una modificación funcional de `calendar.html` para este cambio.

Consecuencia aceptada:

- en modo solo lectura puede seguir apareciendo el modal de edición
- al intentar guardar, la API responderá con error porque el middleware bloqueará el `POST`

Mejora opcional posterior:

- pasar `can_write` al contexto
- ocultar el modal de edición y los controles de guardado cuando `can_write` sea falso
- evitar registrar listeners de edición en modo solo lectura

Esta mejora no es necesaria para proteger los datos, solo para pulir la experiencia de usuario.

## Alexa

`/<secret>/alexa` debe estar disponible solo con el secreto de lectura/escritura.

Motivo:

- Alexa puede responder con notas
- el modo read-only se ha definido como "solo turnos, sin notas"

Implementación prevista:

- permitir `POST /<rw-secret>/alexa`
- devolver `404` o `403` en `POST /<ro-secret>/alexa`

Preferencia: `404`, para no anunciar ese endpoint en la ruta de solo lectura.

## Caché HTTP

Hay que separar la caché por modo o por secreto.

Motivo:

- el HTML de lectura/escritura puede contener notas
- el HTML de solo lectura no debe contener notas
- si el `ETag` usa la misma clave para ambos modos, un navegador o proxy podría revalidar respuestas con contenido distinto bajo una clave equivalente

Cambios previstos:

- ajustar las claves de calendario para incluir el modo:

```text
calendar:read_write:2026-05
calendar:read_only:2026-05
```

- ajustar también `current_month_cache_key`, `settings_cache_key` y `absences_cache_key` si el HTML resultante depende del secreto actual por enlaces `url_for`

Aunque `settings` y `absences` muestren los mismos datos, los enlaces, manifiesto, CSS y acciones JavaScript apuntarán al secreto actual, así que la clave de caché debe distinguir modo o secreto.

## Documentación

Actualizar:

- `README.md`
- `env.example`

Contenido a documentar:

- nueva variable `CALENDARIO_READONLY_SECRET_PATH`
- diferencia entre ruta normal y ruta read-only
- métodos bloqueados en read-only
- las notas no se muestran en el calendario read-only
- `/alexa` no está disponible en read-only

## Pruebas

Pruebas mínimas recomendadas, manuales o automatizadas con test client Flask:

- `GET /<rw-secret>/` devuelve `200`
- `GET /<ro-secret>/` devuelve `200`
- `GET /secreto-invalido/` devuelve `404`
- los enlaces generados desde `/<ro-secret>/` mantienen `/<ro-secret>/`
- `POST /<rw-secret>/api/custom-shift` permite escribir
- `POST /<ro-secret>/api/custom-shift` devuelve error y no modifica la base de datos
- `DELETE /<ro-secret>/api/absences` devuelve error y no modifica la base de datos
- `GET /<ro-secret>/api/rules` sigue funcionando
- `GET /<ro-secret>/api/absences` sigue funcionando
- `POST /<ro-secret>/alexa` no está disponible
- el HTML de `/<ro-secret>/` no contiene texto de notas existentes
- el HTML de `/<rw-secret>/` sí conserva las notas

## Orden De Implementación

### Slice 1. Configuración y resolución de acceso

- añadir `CALENDARIO_READONLY_SECRET_PATH`
- validar ambos secretos
- añadir constantes de modo
- añadir middleware de resolución
- mantener las rutas todavía equivalentes funcionalmente

### Slice 2. Rutas dinámicas y `url_for`

- cambiar decoradores a `/<secret>/...`
- ajustar firmas de vistas
- pasar `secret=g.secret_path` en todos los `url_for`
- verificar navegación desde ambos secretos

### Slice 3. Bloqueo de escritura

- bloquear `POST`, `PUT`, `PATCH`, `DELETE` en read-only
- añadir excepción específica para `/alexa`, dejándola fuera de read-only
- comprobar APIs existentes

### Slice 4. Redacción de notas

- añadir `include_notes` a `CalendarService.build_context`
- pasar `include_notes=False` desde read-only
- comprobar que `data-note` queda vacío en el HTML read-only

### Slice 5. Caché y documentación

- separar claves de caché por modo o secreto
- actualizar `README.md`
- actualizar `env.example`
- hacer comprobación manual de rutas principales

## Riesgos

### Fuga por caché

Riesgo principal. Si las claves de `ETag` no distinguen el modo, se puede servir una versión con notas donde no corresponde.

Mitigación:

- incluir modo o secreto en la clave de recurso cacheada
- probar primero accediendo a la ruta read-write y después a la read-only con la misma sesión/navegador

### Fuga por HTML

Aunque se oculte visualmente una nota, no debe quedar en atributos `data-*`, scripts o JSON embebido.

Mitigación:

- filtrar en el contexto antes de renderizar
- buscar texto de una nota real en el HTML read-only

### Futuros endpoints de escritura

Si en el futuro se añade una API nueva, podría olvidarse el permiso.

Mitigación:

- bloqueo por método en middleware, no por endpoint individual

## Criterio De Aceptación

El cambio se considera completo cuando:

- existen dos secretos configurables
- los dos secretos permiten navegar por la app
- el secreto read-only no permite modificar nada por APIs existentes
- el secreto read-only no expone notas en el HTML del calendario
- los enlaces internos respetan el secreto con el que se entró
- cualquier otro prefijo devuelve `404`
- `/alexa` solo funciona bajo el secreto read-write
