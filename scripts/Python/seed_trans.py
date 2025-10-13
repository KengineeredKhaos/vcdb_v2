from app.slices.auth import services as authsvc

authsvc.assign_role(
    user_id=2,
    role_name="user",
    actor_id="01JABCDETESTADMINULID00001",
    request_id="req-assign-001",
)
authsvc.remove_role(
    user_id=2,
    role_name="user",
    actor_id="01JABCDETESTADMINULID00001",
    request_id="req-remove-001",
)
