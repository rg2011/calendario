from src.httpcache import CacheState
from src.models import Contact, db

SHORTCUTS = ("2", "3", "4", "5", "6", "7", "8", "9", "M1", "M2", "M3")


class ContactService:
    """Gestiona los contactos de marcación abreviada."""

    def __init__(self, cache_state: CacheState) -> None:
        self._cache_state = cache_state

    def contacts_by_shortcut(self) -> dict[str, str]:
        """Devuelve todos los códigos soportados, aunque aún no tengan nombre."""
        contacts = Contact.query.filter(Contact.shortcut.in_(SHORTCUTS)).all()
        names = {contact.shortcut: contact.name for contact in contacts}
        return {shortcut: names.get(shortcut, "") for shortcut in SHORTCUTS}

    def save_contacts(self, data: object) -> tuple[dict[str, object], int]:
        """Guarda de una vez las asociaciones de todos los códigos válidos."""
        if not isinstance(data, dict):
            return {"success": False, "error": "Datos no válidos"}, 400

        for shortcut in SHORTCUTS:
            name = data.get(shortcut, "")
            if not isinstance(name, str):
                return {"success": False, "error": "Datos no válidos"}, 400

            contact = db.session.get(Contact, shortcut)
            if not contact:
                contact = Contact(shortcut=shortcut)  # type: ignore[call-arg]
            contact.name = name.strip()
            db.session.add(contact)

        db.session.commit()
        self._cache_state.touch_data()
        return {"success": True}, 200


def New(cache_state: CacheState) -> ContactService:
    """Construye el servicio de contactos."""
    return ContactService(cache_state=cache_state)
