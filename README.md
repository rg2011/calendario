# Calendario de Turnos

Aplicación web en Flask + SQLite para gestionar un calendario mensual de turnos entre tres personas, con reglas por defecto, sobrescrituras manuales y resaltado de festivos de Sevilla.

## Qué hace

- Muestra el mes en curso en formato calendario.
- Incluye los últimos días del mes anterior y los primeros del siguiente.
- Permite navegar al mes anterior y siguiente.
- Asigna cada día a una de estas personas:
  - `Juanmi`
  - `Rafa`
  - `Ana`
- Permite definir reglas por día de la semana:
  - `fijo`
  - `rotatorio`
- Permite sobrescribir el turno de un día concreto.
- Resalta visualmente:
  - día actual
  - festivos
  - turnos personalizados
  - días sin regla
- Consulta los festivos oficiales de Sevilla mediante la API pública de la Junta de Andalucía.
- Usa caché en memoria para no repetir la consulta de festivos durante la vida del proceso.
- Adapta la UI a móvil, incluyendo abreviaturas y modales táctiles.

## Cómo funciona la asignación

### Regla fija

Siempre asigna la misma persona para ese día de la semana.

Ejemplo:
- todos los lunes `Juanmi`

### Regla rotatoria

Rota semanalmente entre tres personas en el orden configurado, a partir de una fecha inicial.

Ejemplo:
- semana 1: `Juanmi`
- semana 2: `Rafa`
- semana 3: `Ana`
- semana 4: `Juanmi`

### Sobrescritura manual

Desde la vista del calendario se puede abrir un modal sobre un día y asignar una persona distinta al valor por defecto.

## Festivos

La aplicación intenta resolver los festivos de Sevilla usando la API oficial de la Junta de Andalucía:

- provincia: `SEVILLA`
- municipio: `SEVILLA`
- endpoint: `get/search_calendar`

Notas:
- solo se consultan festivos del año en curso
- la caché es solo en memoria
- al arrancar la app, intenta precargar el año actual completo y materializa la caché mensual para evitar la latencia de la primera petición
- al reiniciar la app, la caché se reconstruye
- los festivos locales pueden venir con descripciones genéricas del tipo `FIESTA LOCAL EN SEVILLA (SEVILLA)`

## Seguridad por URL secreta

La app no expone rutas públicas normales. Todas las rutas cuelgan de un prefijo secreto:

```text
/<secreto>/...
```

Ejemplos:

```text
/mi-ruta-secreta/
/mi-ruta-secreta/calendar/2026/4
/mi-ruta-secreta/settings
```

Cualquier otra ruta devuelve `404`.

El secreto se lee de:

- variable de entorno `CALENDARIO_SECRET_PATH`
- o un fichero `.env`

Debe ser un único segmento de ruta, sin `/`.

## Requisitos

- Python `>= 3.13`
- `uv`

## Instalación

### 1. Entrar en el proyecto

```bash
cd /home/rafa/projects/calendario
```

### 2. Instalar dependencias

```bash
uv sync
```

Si prefieres añadir o actualizar dependencias:

```bash
uv add <paquete>
```

## Configuración

Crea un fichero `.env` en la raíz del proyecto:

```env
CALENDARIO_SECRET_PATH=mi-ruta-secreta-123
FLASK_RUN_HOST=127.0.0.1
FLASK_RUN_PORT=5000
```

Variables relevantes:

- `CALENDARIO_SECRET_PATH`
  - obligatoria
  - define el prefijo secreto de la URL
- `FLASK_RUN_HOST`
  - opcional
  - por defecto `127.0.0.1`
- `FLASK_RUN_PORT`
  - opcional
  - por defecto `5000`

## Arranque

```bash
uv run python app.py
```

Al arrancar, la app muestra en consola una línea similar a:

```text
Escuchando en http://127.0.0.1:5000/mi-ruta-secreta-123
```

## Uso

### Calendario

- navega entre meses con las flechas de cabecera
- usa `Mes actual` en la barra superior para volver al mes en curso
- pulsa sobre el bloque del turno para editar la asignación del día
- pulsa sobre el número del día si es festivo para abrir el modal del festivo

### Configuración

En la pantalla de configuración puedes definir para cada día de la semana:

- algoritmo
- persona fija
- orden de rotación
- fecha de inicio de la rotación

## Persistencia

La aplicación usa SQLite para guardar:

- reglas por día de la semana
- turnos personalizados por fecha

Las tablas principales son:

### `day_week_rules`

- `day_of_week`
- `algorithm`
- `person_fijo`
- `rotation_order`
- `rotation_start_date`

### `custom_shifts`

- `shift_date`
- `person`

La base de datos se crea automáticamente en `instance/calendar.db`.

## Estructura principal

```text
calendario/
├── app.py
├── models.py
├── pyproject.toml
├── uv.lock
├── templates/
│   ├── base.html
│   ├── calendar.html
│   └── settings.html
├── static/
│   └── style.css
└── instance/
    └── calendar.db
```

## Desarrollo

Comprobación rápida de sintaxis:

```bash
python3 -m py_compile app.py models.py
```

La aplicación arranca actualmente en modo debug desde `app.py`.

Si la vas a exponer a Internet, conviene revisar eso antes de desplegarla.

## Despliegue con Podman Quadlet

Si clonas el proyecto en `/opt/calendario`, copia estos ficheros a:

```text
/etc/containers/systemd/calendario.container
/etc/containers/systemd/calendario.build
```

Suposiciones de ese quadlet:

- ejecuta el contenedor como `uid 1000` y `gid 1000`
- construye la imagen desde `/opt/calendario/Dockerfile`
- monta `/opt/calendario/instance` en `/app/instance`
- lee variables desde `/opt/calendario/.env`
- usa sistema de ficheros de solo lectura en el contenedor, salvo el bind mount de `instance`
- publica el puerto `5000`

Activación:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now calendario.service
```

## Despliegue con systemd sin Quadlet

Si prefieres no usar Quadlet, puedes copiar [`calendario.service`](/mnt/wsl/tank/projects/calendario/calendario.service) a:

```text
/etc/systemd/system/calendario.service
```

Ese servicio:

- ejecuta la app directamente desde `/opt/calendario`
- usa `uid 1000` y `gid 1000`
- arranca con `uv run python app.py`
- lee variables desde `/opt/calendario/.env`

Activación:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now calendario.service
```

## Fuente de festivos

- API oficial de la Junta de Andalucía:
  - `https://datos.juntadeandalucia.es/api/v0/work-calendar/openapi.json`
- Página oficial del Ayuntamiento de Sevilla para contraste manual:
  - `https://www.sevilla.org/fiestas-de-la-ciudad/festivos-locales`

## Licencia

Proyecto de uso libre para este calendario.
