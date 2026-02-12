# Request envelope (what Extensions expects from slices calling the contract):
#json

{
  "contract": "ledger.emit.v1",
  "request_id": "01J...",
  "dry_run": false,
  "data": {
    "type": "role.adjust",
    "domain": "admin",
    "operation": "add",
    "request_id": "01J...",   // same or upstream request id
    "actor_id": "01H...entity",
    "target_id": "01H...entity",
    "changed_fields_json": {"roles_added":["customer"]},
    "refs_json": {"reason":"admin_fix"}
  }
}


# Response DTO (current minimal):
# json

{
  "contract": "ledger.emit.v1",
  "request_id": "01J...",
  "ts": "2025-09-30T12:34:56Z",
  "ok": true,
  "data": {
    "id": "01J...event",
    "event_hash": "a9e9...",
    "preview": false
  }
}
