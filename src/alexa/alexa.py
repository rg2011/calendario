import re
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src.shifts.service import ShiftService

LOCAL_TZ = ZoneInfo('Europe/Madrid')
CONVERSATION_REPROMPT = '¿Quieres consultar otra fecha? Dime el día que quieras saber.'
ALEXA_FAREWELL_UTTERANCES = {
    'adios',
    'hasta luego',
    'nos vemos',
    'salir',
    'cierra',
    'gracias',
    'cancela',
    'cancelar',
    'basta',
    'para ya',
}


class AlexaHandler:
    """Gestiona la resolución de intents y respuestas del webhook Alexa."""

    def __init__(self, skill_id: str, shift_service: ShiftService) -> None:
        self._skill_id = skill_id.strip()
        self._shift_service = shift_service

    def verify_skill_id(self, payload: dict[str, object]) -> bool:
        """Comprueba el `applicationId` si la app exige un skill id concreto."""
        if not self._skill_id:
            return True

        application = (
            (payload or {})
            .get('context', {})
            .get('System', {})
            .get('application', {})
        )
        if not isinstance(application, dict):
            return False
        request_skill_id = (application.get('applicationId') or '').strip()
        return request_skill_id == self._skill_id

    def handle_request(self, payload: dict[str, object]) -> dict[str, object]:
        """Procesa una request Alexa y devuelve el envelope de respuesta."""
        request_envelope = (payload or {}).get('request') or {}
        if not isinstance(request_envelope, dict):
            return self._plain_text_response('No he podido procesar esa petición.')

        request_type = request_envelope.get('type')

        if request_type == 'LaunchRequest':
            return self._plain_text_response(
                'Hola. Puedo decirte quién tiene turno en cualquier día.',
                should_end_session=False,
                reprompt_text='¿Quieres saber quién tiene turno hoy? Dime una fecha.',
            )

        if request_type == 'IntentRequest':
            intent = request_envelope.get('intent') or {}
            if not isinstance(intent, dict):
                return self._plain_text_response('No he podido procesar esa petición.')
            intent_name = intent.get('name')

            if intent_name == 'QueryShiftIntent':
                return self._handle_query_shift_intent(intent)
            if intent_name == 'QueryNotesIntent':
                return self._handle_query_notes_intent(intent)
            if intent_name == 'AMAZON.HelpIntent':
                return self._conversational_response(
                    'Puedes preguntarme quién va con los padres en cualquier fecha '
                    'o qué notas hay apuntadas. '
                    'Por ejemplo: ¿quién viene hoy? o ¿qué notas hay mañana?'
                )
            if intent_name in {'AMAZON.StopIntent', 'AMAZON.CancelIntent'}:
                return self._plain_text_response('Hasta luego.')
            if intent_name == 'AMAZON.FallbackIntent':
                if self._should_end_session_for_fallback(payload):
                    return self._plain_text_response('Hasta luego.')
                return self._conversational_response(
                    'No te he entendido. Prueba preguntando quién va con los padres hoy '
                    'o qué notas hay mañana.'
                )

        return self._plain_text_response('No he podido procesar esa petición.')

    def _resolve_simple_alexa_date(
        self,
        slot_value: str,
        today: date | None = None,
    ) -> tuple[dict[str, object] | None, str | None]:
        if not slot_value:
            return None, 'No has indicado ninguna fecha.'

        today = today or datetime.now(LOCAL_TZ).date()
        raw = slot_value.strip()

        if raw == 'PRESENT_REF':
            return {'kind': 'date', 'date': today}, None

        if len(raw) == 10 and raw[:4].isdigit() and raw[4] == '-' and raw[7] == '-':
            try:
                return {'kind': 'date', 'date': datetime.fromisoformat(raw).date()}, None
            except ValueError:
                return None, 'No he podido interpretar esa fecha.'

        if raw.startswith('XXXX-') and len(raw) == 10:
            try:
                month = int(raw[5:7])
                day = int(raw[8:10])
                candidate = date(today.year, month, day)
            except ValueError:
                return None, 'No he podido interpretar esa fecha.'
            if candidate < today:
                try:
                    candidate = date(today.year + 1, month, day)
                except ValueError:
                    return None, 'No he podido interpretar esa fecha.'
            return {'kind': 'date', 'date': candidate}, None

        weekend_match = re.fullmatch(r'(\d{4})-W(\d{2})-WE', raw)
        if weekend_match:
            year = int(weekend_match.group(1))
            week = int(weekend_match.group(2))
            try:
                saturday = date.fromisocalendar(year, week, 6)
                sunday = date.fromisocalendar(year, week, 7)
            except ValueError:
                return None, 'No he podido interpretar ese fin de semana.'
            return {'kind': 'weekend', 'dates': [saturday, sunday]}, None

        return None, (
            'Todavia no soporte ese formato de fecha. '
            'Por ahora prueba con hoy o con una fecha concreta como el quince de mayo.'
        )

    def _get_shift_summary_for_target(self, resolved_target: dict[str, object]) -> dict[str, object]:
        if resolved_target['kind'] == 'date':
            target_date = resolved_target['date']
            assert isinstance(target_date, date)
            return {
                'kind': 'date',
                'summary': self._shift_service.get_shift_summary_for_date(target_date),
            }

        target_dates = resolved_target['dates']
        assert isinstance(target_dates, list)
        daily_summaries = [
            self._shift_service.get_shift_summary_for_date(target_date)
            for target_date in target_dates
        ]
        people: list[str] = []
        for summary in daily_summaries:
            person = summary.get('person')
            if isinstance(person, str) and person not in people:
                people.append(person)
        notes = [
            {
                'date': summary['date'],
                'speech_date': self._format_date_for_speech(summary['date']),
                'note': summary['note'].strip(),
            }
            for summary in daily_summaries
            if isinstance(summary.get('note'), str) and summary['note'].strip()
        ]
        return {
            'kind': 'weekend',
            'dates': target_dates,
            'daily_summaries': daily_summaries,
            'people': people,
            'notes': notes,
        }

    def _handle_query_shift_intent(self, intent: dict[str, object]) -> dict[str, object]:
        slots = intent.get('slots') or {}
        if not isinstance(slots, dict):
            slots = {}
        date_slot = slots.get('target_date') or {}
        if not isinstance(date_slot, dict):
            date_slot = {}
        slot_value = (date_slot.get('value') or '').strip()
        resolved_target, error_message = self._resolve_simple_alexa_date(slot_value)
        if error_message:
            return self._conversational_response(error_message)
        assert resolved_target is not None

        target_summary = self._get_shift_summary_for_target(resolved_target)
        if target_summary['kind'] == 'weekend':
            target_dates = target_summary['dates']
            people = target_summary['people']
            notes = target_summary['notes']
            assert isinstance(target_dates, list)
            assert isinstance(people, list)
            assert isinstance(notes, list)
            speech_date = self._format_weekend_for_speech(target_dates)
            if not people:
                speech = f'Para {speech_date} no tengo ninguna persona asignada.'
            elif len(people) == 1:
                speech = f'Para {speech_date} le toca a {self._join_people_for_speech(people)}.'
            else:
                speech = f'Para {speech_date} les toca a {self._join_people_for_speech(people)}.'
            if notes:
                speech += f" Hay estas notas: {self._format_enumerated_notes_for_speech(notes)}"
            return self._conversational_response(speech)

        summary = target_summary['summary']
        assert isinstance(summary, dict)
        speech_date = self._format_date_for_speech(summary['date'])
        person = summary['person']
        note = summary.get('note')
        if not person:
            speech = f'El {speech_date} no tengo ninguna persona asignada.'
            if note:
                speech += f' Pero hay una nota: {note}'
            return self._conversational_response(speech)

        speech = f'El {speech_date} le toca a {person}.'
        if note:
            speech += f' Hay una nota: {note}'
        return self._conversational_response(speech)

    def _handle_query_notes_intent(self, intent: dict[str, object]) -> dict[str, object]:
        slots = intent.get('slots') or {}
        if not isinstance(slots, dict):
            slots = {}
        date_slot = slots.get('target_date') or {}
        if not isinstance(date_slot, dict):
            date_slot = {}
        slot_value = (date_slot.get('value') or '').strip()
        resolved_target, error_message = self._resolve_simple_alexa_date(slot_value)
        if error_message:
            return self._conversational_response(error_message)
        assert resolved_target is not None

        target_summary = self._get_shift_summary_for_target(resolved_target)
        if target_summary['kind'] == 'weekend':
            target_dates = target_summary['dates']
            notes = target_summary['notes']
            people = target_summary['people']
            assert isinstance(target_dates, list)
            assert isinstance(notes, list)
            assert isinstance(people, list)
            speech_date = self._format_weekend_for_speech(target_dates)
            people_clause = ''
            if people:
                if len(people) == 1:
                    people_clause = f' Le toca a {self._join_people_for_speech(people)}.'
                else:
                    people_clause = f' Les toca a {self._join_people_for_speech(people)}.'
            if not notes:
                return self._conversational_response(
                    f'Para {speech_date} no hay ninguna nota apuntada.{people_clause}'
                )
            return self._conversational_response(
                f'Para {speech_date} tengo estas notas: '
                f'{self._format_enumerated_notes_for_speech(notes)}.{people_clause}'
            )

        summary = target_summary['summary']
        assert isinstance(summary, dict)
        speech_date = self._format_date_for_speech(summary['date'])
        note = (summary.get('note') or '').strip()
        if not note:
            return self._conversational_response(f'El {speech_date} no hay ninguna nota apuntada.')
        return self._conversational_response(f'Para el {speech_date} tengo esta nota: {note}')

    def _conversational_response(self, text: str) -> dict[str, object]:
        return self._plain_text_response(
            text,
            should_end_session=False,
            reprompt_text=CONVERSATION_REPROMPT,
        )

    def _plain_text_response(
        self,
        text: str,
        should_end_session: bool = True,
        reprompt_text: str | None = None,
    ) -> dict[str, object]:
        response_body: dict[str, object] = {
            'outputSpeech': {
                'type': 'PlainText',
                'text': text,
            },
            'shouldEndSession': should_end_session,
        }
        if reprompt_text is not None:
            response_body['reprompt'] = {
                'outputSpeech': {
                    'type': 'PlainText',
                    'text': reprompt_text,
                }
            }
        return {
            'version': '1.0',
            'response': response_body,
        }

    def _format_date_for_speech(self, target_date: date) -> str:
        weekday_names = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']
        month_names = {
            1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril', 5: 'mayo', 6: 'junio',
            7: 'julio', 8: 'agosto', 9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre',
        }
        weekday_name = weekday_names[target_date.weekday()]
        return f'{weekday_name} {target_date.day} de {month_names[target_date.month]}'

    def _format_weekend_for_speech(self, target_dates: list[date]) -> str:
        saturday, sunday = target_dates
        if saturday.month == sunday.month:
            month_names = {
                1: 'enero', 2: 'febrero', 3: 'marzo', 4: 'abril', 5: 'mayo', 6: 'junio',
                7: 'julio', 8: 'agosto', 9: 'septiembre', 10: 'octubre', 11: 'noviembre', 12: 'diciembre',
            }
            return (
                f'el fin de semana del sabado {saturday.day} '
                f'y domingo {sunday.day} de {month_names[saturday.month]}'
            )
        return (
            f'el fin de semana del {self._format_date_for_speech(saturday)} '
            f'y {self._format_date_for_speech(sunday)}'
        )

    def _normalize_alexa_utterance(self, text: str) -> str:
        if not text:
            return ''
        normalized = unicodedata.normalize('NFD', text.strip().lower())
        ascii_like = ''.join(char for char in normalized if unicodedata.category(char) != 'Mn')
        cleaned = ''.join(char if char.isalnum() or char.isspace() else ' ' for char in ascii_like)
        return ' '.join(cleaned.split())

    def _extract_alexa_transcript(self, payload: dict[str, object]) -> str:
        request_envelope = (payload or {}).get('request') or {}
        if not isinstance(request_envelope, dict):
            return ''
        intent = request_envelope.get('intent') or {}
        if not isinstance(intent, dict):
            intent = {}
        candidate_values = [
            request_envelope.get('transcript'),
            request_envelope.get('inputTranscript'),
            request_envelope.get('utterance'),
            intent.get('transcript'),
            intent.get('inputTranscript'),
            intent.get('utterance'),
        ]
        for value in candidate_values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ''

    def _should_end_session_for_fallback(self, payload: dict[str, object]) -> bool:
        transcript = self._normalize_alexa_utterance(self._extract_alexa_transcript(payload))
        if not transcript:
            return False
        transcript_tokens = transcript.split()
        transcript_token_count = len(transcript_tokens)
        for farewell in ALEXA_FAREWELL_UTTERANCES:
            farewell_tokens = farewell.split()
            farewell_token_count = len(farewell_tokens)
            if farewell_token_count == 0 or farewell_token_count > transcript_token_count:
                continue
            for start_index in range(transcript_token_count - farewell_token_count + 1):
                if transcript_tokens[start_index:start_index + farewell_token_count] == farewell_tokens:
                    return True
        return False

    def _join_people_for_speech(self, people: list[str]) -> str:
        if not people:
            return ''
        if len(people) == 1:
            return people[0]
        if len(people) == 2:
            return f'{people[0]} y {people[1]}'
        return f"{', '.join(people[:-1])} y {people[-1]}"

    def _format_enumerated_notes_for_speech(self, notes: list[dict[str, object]]) -> str:
        if not notes:
            return ''
        note_parts = [f"{note['speech_date']}: {note['note']}" for note in notes]
        if len(note_parts) == 1:
            return note_parts[0]
        return '; '.join(note_parts)


def New(skill_id: str, shift_service: ShiftService) -> AlexaHandler:
    """Construye el handler Alexa."""
    return AlexaHandler(skill_id=skill_id, shift_service=shift_service)
