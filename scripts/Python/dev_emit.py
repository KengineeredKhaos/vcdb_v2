#!/usr/bin/env python3
"""
Dev emitter for VCDB v2
Usage:
  python scripts/dev_emit.py assign-role 2 user
  python scripts/dev_emit.py assign-role 2 user --force-emit
  python scripts/dev_emit.py remove-role 2 user
  python scripts/dev_emit.py policy-set staff_spend_cap_cents 25000
"""
import argparse
import os
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import create_app

APP = create_app("config.DevConfig")


def uniq_req(prefix):
    return f"{prefix}-{int(time.time()*1000)}"


def main():
    parser = argparse.ArgumentParser(prog="dev_emit")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_assign = sub.add_parser("assign-role")
    p_assign.add_argument("user_id", type=int)
    p_assign.add_argument("role_name")
    p_assign.add_argument(
        "--actor", dest="actor_id", default="01JADMINULIDEXAMPLE0000000001"
    )
    p_assign.add_argument("--req", dest="request_id", default=None)
    p_assign.add_argument("--force-emit", action="store_true")

    p_remove = sub.add_parser("remove-role")
    p_remove.add_argument("user_id", type=int)
    p_remove.add_argument("role_name")
    p_remove.add_argument(
        "--actor", dest="actor_id", default="01JADMINULIDEXAMPLE0000000001"
    )
    p_remove.add_argument("--req", dest="request_id", default=None)

    p_policy = sub.add_parser("policy-set")
    p_policy.add_argument("key")
    p_policy.add_argument("value")
    p_policy.add_argument(
        "--actor", dest="actor_id", default="01JADMINULIDEXAMPLE0000000001"
    )
    p_policy.add_argument("--req", dest="request_id", default=None)

    args = parser.parse_args()
    with APP.app_context():
        if args.cmd == "assign-role":
            from sqlalchemy import and_, exists, insert, select

            from app.extensions import db, event_bus
            from app.slices.auth.models import Role, User, UserRole

            req = args.request_id or uniq_req("req-assign")
            # ensure user exists
            uid = db.session.execute(
                select(User.id).where(User.id == args.user_id)
            ).scalar()
            if uid is None:
                print(f"ERR: user {args.user_id} not found")
                sys.exit(1)
            # ensure role id
            rid = db.session.execute(
                select(Role.id).where(Role.name == args.role_name)
            ).scalar()
            if rid is None:
                db.session.execute(insert(Role).values(name=args.role_name))
                db.session.commit()
                rid = db.session.execute(
                    select(Role.id).where(Role.name == args.role_name)
                ).scalar_one()

            link_exists = db.session.execute(
                select(
                    exists().where(
                        and_(UserRole.user_id == uid, UserRole.role_id == rid)
                    )
                )
            ).scalar()

            emitted = False
            if not link_exists:
                db.session.execute(
                    insert(UserRole).values(user_id=uid, role_id=rid)
                )
                db.session.commit()
                event_bus.emit(
                    type="auth.user_role.assigned",
                    slice="auth",
                    operation="assigned",
                    happened_at_utc=datetime.now(timezone.utc),
                    actor_ulid=args.actor_id,
                    target_ulid=str(uid),
                    entity_ids={"role": args.role_name},
                    request_id=req,
                )
                emitted = True
                print(f"OK assigned role (link created), emitted, req={req}")
            else:
                if args.force_emit:
                    event_bus.emit(
                        type="auth.user_role.assigned",
                        slice="auth",
                        operation="assigned",
                        happened_at_utc=datetime.now(timezone.utc),
                        actor_ulid=args.actor_id,
                        target_ulid=str(uid),
                        entity_ids={"role": args.role_name},
                        request_id=req,
                    )
                    emitted = True
                    print(
                        f"OK role already present; forced emission, req={req}"
                    )
                else:
                    print(
                        "SKIP: role already present; no emission (by design)."
                    )

        elif args.cmd == "remove-role":
            from sqlalchemy import and_, delete, select

            from app.extensions import db, event_bus
            from app.slices.auth.models import Role, UserRole

            req = args.request_id or uniq_req("req-remove")
            rid = db.session.execute(
                select(Role.id).where(Role.name == args.role_name)
            ).scalar()
            if rid is None:
                print("SKIP: role does not exist; nothing to remove.")
                return
            res = db.session.execute(
                delete(UserRole).where(
                    and_(
                        UserRole.user_id == args.user_id,
                        UserRole.role_id == rid,
                    )
                )
            )
            if res.rowcount:
                db.session.commit()
                event_bus.emit(
                    type="auth.user_role.removed",
                    slice="auth",
                    operation="removed",
                    happened_at_utc=datetime.now(timezone.utc),
                    actor_ulid=args.actor_id,
                    target_ulid=str(args.user_id),
                    entity_ids={"role": args.role_name},
                    request_id=req,
                )
                print(f"OK removed link, emitted, req={req}")
            else:
                print("SKIP: link not present; nothing to remove.")

        elif args.cmd == "policy-set":
            from app.slices.governance import services as govsvc

            req = args.request_id or uniq_req("req-policy")
            govsvc.policy_set(
                args.key, args.value, actor_ulid=args.actor_id, request_id=req
            )
            print(f"OK policy-set {args.key}={args.value}, req={req}")


if __name__ == "__main__":
    main()
