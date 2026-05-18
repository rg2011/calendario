# Plan: Personas Configurables

## Objetivo

Eliminar las dependencias hard-codeadas de `Juanmi`, `Rafa`, `Ana`, sus abreviaturas
`J`, `R`, `A` y el supuesto de que siempre hay exactamente tres personas.

La lista de personas debe venir de configuracion, no de la base de datos. Todas
las funcionalidades deben adaptarse a esa configuracion:

- calendario mensual
- modal de edicion de turnos
- reglas fijas
- reglas rotatorias
- ausencias
- respuestas de Alexa
- documentacion y validaciones

## Decision Principal

Usar variables de entorno como fuente de verdad.

Formato propuesto:

```env
PERSONA_NOMBRE_1=Juanmi
PERSONA_ABREVIATURA_1=J
PERSONA_NOMBRE_2=Rafa
PERSONA_ABREVIATURA_2=R
PERSONA_NOMBRE_3=Ana
PERSONA_ABREVIATURA_3=A
```

El indice numerico define el orden de presentacion y el orden por defecto para
rotaciones nuevas.

No se anade tabla `Person`. No se introduce una clave interna. El nombre sigue
siendo el identificador funcional y coincide con lo que ya guardan:

- `day_week_rules.person_fijo`
- `day_week_rules.rotation_order`
- `custom_shifts.person`
- `absences.person`

Ventaja: no hay migracion de datos para referencias existentes.

Tradeoff aceptado: cambiar un nombre en la configuracion equivale a cambiar la
identidad. Si alguna vez hiciera falta un renombrado real, se haria una
migracion puntual de datos.

## Situacion Actual

Puntos principales detectados:

- `app.py` define `PEOPLE = ["Juanmi", "Rafa", "Ana"]` y lo inyecta en servicios y
  plantillas.
- `src/shifts/service.py` rechaza rotaciones si `len(people_list) != 3`.
- `templates/settings.html` genera exactamente tres selectores de rotacion:
  `rot_1`, `rot_2`, `rot_3`.
- `templates/calendar.html` contiene clases y abreviaturas por persona:
  `person-juanmi`, `person-rafa`, `person-ana`, `J`, `R`, `A`.
- `static/style.css` define colores especificos para esas tres personas.
- Las tablas actuales guardan la persona como texto por nombre.
- Alexa no tiene nombres hard-codeados, pero consume el resumen de turnos; debe
  seguir usando nombres de presentacion desde la configuracion.

## Modelo De Configuracion

Crear un modulo nuevo, por ejemplo `src/people/config.py`.

Objeto de dominio:

```python
@dataclass(frozen=True)
class Person:
    name: str
    abbreviation: str
    sort_order: int
```

Funciones propuestas:

- `load_people_from_env(environ: Mapping[str, str]) -> list[Person]`
- `people_by_name(people: list[Person]) -> dict[str, Person]`
- `validate_people_config(people: list[Person]) -> None`

Reglas de carga:

- buscar variables que cumplan `PERSONA_NOMBRE_<n>`
- ordenar por `<n>` numerico
- exigir `PERSONA_ABREVIATURA_<n>` para cada nombre
- rechazar nombres vacios
- rechazar abreviaturas vacias
- rechazar nombres duplicados
- rechazar indices no numericos
- si no hay personas configuradas, fallar al arrancar o usar fallback explicito

Recomendacion: para no romper despliegues existentes, usar fallback temporal:

```python
[
    Person("Juanmi", "J", 1),
    Person("Rafa", "R", 2),
    Person("Ana", "A", 3),
]
```

Ese fallback debe quedar documentado como compatibilidad. Si se prefiere
configuracion estricta, se puede eliminar mas adelante y exigir variables de
entorno.

## Fase 1. Cargar Personas Desde Entorno

Eliminar `PEOPLE` de `app.py`.

En `app.py`:

- llamar a `load_people_from_env(os.environ)` despues de `load_dotenv()`
- pasar `people` a los servicios
- pasar `people` a plantillas

Importante: como las personas vienen de entorno, se pueden cargar una vez al
arrancar. No hace falta invalidacion dinamica ni consultas a DB.

Actualizar `env.example`:

```env
PERSONA_NOMBRE_1=Juanmi
PERSONA_ABREVIATURA_1=J
PERSONA_NOMBRE_2=Rafa
PERSONA_ABREVIATURA_2=R
PERSONA_NOMBRE_3=Ana
PERSONA_ABREVIATURA_3=A
```

## Fase 2. Servicios De Dominio Sin Lista Estatica

Cambiar `AbsenceService`, `ShiftService` y `CalendarService` para recibir
`list[Person]` en vez de `list[str]`.

Cambios concretos:

- construir internamente `people_names = {person.name for person in people}`
- `AbsenceService.save_absence`: validar `person` contra nombres configurados
- `AbsenceService.get_absences_for_dates`: puede seguir devolviendo nombres
- `ShiftService.get_default_shift_for_day`: quitar `len(people_list) != 3`
- `ShiftService.get_default_shift_for_day`: rotar usando `len(rotation_order)`
- `ShiftService.save_rule`: validar que `person_fijo` y cada elemento de
  `rotation_order` existen en la configuracion
- `ShiftService.set_custom_shift`: validar `person` contra nombres configurados
- `CalendarService.build_context`: enriquecer cada dia con:
  - `person_abbreviation`
  - `person_color_class`
  - fallback de abreviatura si aparece un nombre historico no configurado

Regla para nombres no configurados en datos existentes:

- no permitir nuevas asignaciones a personas fuera de configuracion
- si un dato historico apunta a un nombre no configurado, mostrar el nombre tal
  cual y usar una abreviatura derivada, por ejemplo la primera letra

Esto evita que una configuracion nueva deje el calendario ilegible.

## Fase 3. UI Dinamica

### Calendario

En `templates/calendar.html`:

- sustituir condicionales por persona por datos ya calculados:
  `day.person_color_class`, `day.person`, `day.person_abbreviation`
- generar los botones del modal con `{% for person in people %}`
- enviar `person.name` en `data-person`
- usar `day.person_abbreviation` para la vista movil
- mantener `Vacío`/`X` como fallback cuando no haya persona asignada

En `static/style.css`:

- reemplazar clases `person-juanmi`, `person-rafa`, `person-ana`
- crear una paleta generica, por ejemplo `person-color-0` a `person-color-7`
- mantener un fallback para personas por encima de la paleta

### Reglas

En `templates/settings.html`:

- eliminar los tres selectores fijos `rot_1`, `rot_2`, `rot_3`
- renderizar tantos controles como personas configuradas haya
- usar una coleccion DOM comun, por ejemplo
  `[data-rotation-person][data-day="{{ day_num }}"]`
- al guardar, construir `rotation_order` con todos los nombres seleccionados
- validar duplicados antes del `fetch` para dar feedback inmediato

Primera version recomendada: cada regla rotatoria usa todas las personas
configuradas en el orden elegido. Asi la UI no necesita controles para
anadir/quitar filas de rotacion desde el principio.

### Ausencias

En `templates/absences.html`:

- usar `person.name` como valor del select
- mostrar `person.name`
- las ausencias historicas de personas no configuradas pueden mostrarse en la
  lista, pero no apareceran como opcion para nuevas ausencias

## Fase 4. APIs

No hace falta crear endpoints de gestion de personas.

Los payloads existentes pueden mantener el campo `person` como nombre:

- reglas: `person_fijo` y `rotation_order` contienen nombres
- turnos personalizados: `person` contiene nombre
- ausencias: `person` contiene nombre

Anadir opcionalmente un endpoint de solo lectura para depuracion o UI:

- `GET /api/people`

Este endpoint devolveria la configuracion cargada:

```json
[
  {"name": "Juanmi", "abbreviation": "J", "sort_order": 1},
  {"name": "Rafa", "abbreviation": "R", "sort_order": 2},
  {"name": "Ana", "abbreviation": "A", "sort_order": 3}
]
```

## Fase 5. Alexa

Alexa puede seguir consumiendo `summary["person"]` como nombre.

Cambios esperados:

- no introducir claves internas
- mantener `_join_people_for_speech` con nombres
- comprobar que nombres historicos no configurados siguen pronunciandose si
  aparecen en reglas o turnos antiguos

## Fase 6. Documentacion Y Verificacion

Actualizar `README.md`:

- sustituir "entre tres personas" por "entre personas configurables"
- documentar `PERSONA_NOMBRE_<n>` y `PERSONA_ABREVIATURA_<n>`
- explicar que las rotaciones pueden tener cualquier numero de personas
- aclarar que el nombre es identidad funcional
- actualizar `env.example`

Verificaciones minimas:

- `uv run ruff check .`
- `uv run pyright`
- `uv run python -m py_compile app.py` y compilar los modulos de `src`
- prueba manual:
  - arrancar la app sin variables nuevas y comprobar el fallback, si se mantiene
  - arrancar con tres personas configuradas
  - anadir una cuarta persona por entorno
  - configurar una rotacion de cuatro personas
  - comprobar varias semanas consecutivas
  - crear una ausencia para la nueva persona
  - crear un turno personalizado para la nueva persona
  - comprobar la vista movil y abreviaturas
  - probar webhook Alexa con `tools/test_alexa_webhook.py`

## Riesgos

- `name` como identidad implica que no hay renombrado transparente. Es una
  limitacion asumida para simplificar.
- `rotation_order` es un string CSV. Se mantiene para reducir alcance, pero no
  permite nombres con coma.
- Cambiar variables de entorno requiere reiniciar la aplicacion.
- Si la configuracion elimina una persona con datos historicos, hay que mostrar
  esos datos con fallback visual sin permitir nuevas asignaciones.
- Si hay mas personas que colores definidos, debe existir fallback visual
  legible.

## Criterios De Aceptacion

- No queda ninguna referencia funcional hard-codeada a `Juanmi`, `Rafa`, `Ana`,
  `J`, `R`, `A` fuera del fallback/documentacion de compatibilidad.
- No hay ninguna validacion que asuma exactamente tres personas.
- La UI renderiza correctamente con 1, 2, 3, 4 o mas personas configuradas.
- Las rotaciones usan `len(rotation_order)` y no una constante fija.
- Los datos existentes siguen funcionando sin migrar sus referencias.
- Alexa responde con nombres visibles.
