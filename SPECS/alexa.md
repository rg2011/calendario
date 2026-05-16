# Skill Alexa

La aplicación debe implementar un skill de alexa que permita interactuar con el calendario.

El objetivo del calendario es gestionar los turnos para atender a los padres. Todas las preguntas están relacionadas con la persona a la que le toca atender a los padres en una cierta fecha, o las notas que se han dejado para esa fecha. El tipo de preguntas que vamos a soportar son:

- ¿A quien le toca <fecha>?
- ¿Quien viene <fecha>?
- ¿Quien va con los padres <fecha>?

En todos los casos, se refiere a lo mismo: quien va a estar rpesencialmente cuidando de los padres en esa fecha. En algunos casos, se pueden dejar notas para esa fecha, y el skill también debe ser capaz de responder a preguntas como:

- ¿Que notas hay para <fecha>?
- ¿Que hay para <fecha>?
- Leeme las notas de <fecha>

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
