# app/slices/transactions/routes.py  (excerpt)
from flask import render_template, request

from app.utils.paging import Pager, pagination_args

from .models import LedgerEvent, db


@bp.get("/ledger")
@login_required
def ledger_index():
    # read filters + paging
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 25)), 200)
    etype = request.args.get("type")
    slc = request.args.get("slice")

    q = db.session.query(LedgerEvent)
    if etype:
        q = q.filter(LedgerEvent.type == etype)
    if slc:
        q = q.filter(LedgerEvent.slice == slc)

    total = q.count()
    rows = (
        q.order_by(LedgerEvent.happened_at_utc.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    p = Pager(total=total, page=page, per_page=per_page)
    qargs = pagination_args(request)  # preserve current filters

    return render_template(
        "transactions/ledger.html", rows=rows, p=p, qargs=qargs
    )
