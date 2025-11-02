# app/extensions/entity_api.py


# -----------------
# Entity API
# -----------------
class _EntityAPI:
    def __init__(self):
        self._impl = {}

    def register(self, **impl):
        self._impl.update(impl)

    # stable signatures
    def ensure_person(self, **kw):
        return self._impl["ensure_person"](**kw)

    def ensure_org(self, **kw):
        return self._impl["ensure_org"](**kw)

    def upsert_contacts(self, **kw):
        return self._impl["upsert_contacts"](**kw)

    def upsert_address(self, **kw):
        return self._impl["upsert_address"](**kw)

    def ensure_role(self, **kw):
        return self._impl["ensure_role"](**kw)


entity_api = _EntityAPI()

__all__ = ["entity_api", "_EntityAPI"]
