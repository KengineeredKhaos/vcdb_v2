# app/extensions/entity_read.py

# -----------------
# Entity read-side Facade
# -----------------


class EntityReadFacade:
    def __init__(self):
        self._impl = {}

    def register(self, **kw):
        self._impl.update(kw)

    def list_people_with_role(self, role_code: str, page: int, per: int):
        fn = self._impl.get("list_people_with_role")
        if not fn:
            raise RuntimeError(
                "entity_read.list_people_with_role not registered"
            )
        return fn(role_code=role_code, page=page, per=per)

    def person_view(self, person_id: str):
        fn = self._impl.get("person_view")
        if not fn:
            raise RuntimeError("entity_read.person_view not registered")
        return fn(person_id=person_id)


entity_read = EntityReadFacade()
