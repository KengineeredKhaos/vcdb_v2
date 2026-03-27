# app/slices/admin/routes.py

"""
VCDB v2 — Admin slice routes


"""

from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import login_required

from app.lib.security import roles_required

from . import services as svc

bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
    template_folder="templates",
)


# -----------------
# Dashboard
# -----------------


@bp.get("/")
@login_required
@roles_required("admin")
def index():
    page = svc.get_dashboard()
    return render_template("admin/index.html", page=page)


# -----------------
# Unified Admin Inbox
# -----------------


@bp.get("/inbox/")
@login_required
@roles_required("admin")
def inbox():
    page = svc.get_inbox_page()
    return render_template("admin/inbox.html", page=page)


# -----------------
# Cron & Maint
# -----------------


@bp.get("/cron/")
@login_required
@roles_required("admin")
def cron():
    page = svc.get_cron_page()
    return render_template("admin/cron.html", page=page)


# -----------------
# Policy Workflow
# -----------------


@bp.get("/policy/")
@login_required
@roles_required("admin")
def policy_index():
    page = svc.get_policy_index_page()
    return render_template("admin/policy/index.html", page=page)


# -----------------
# Auth Surface
# Operator Mngmt
# -----------------


@bp.get("/auth/operators/")
@login_required
@roles_required("admin")
def auth_operators():
    page = svc.get_auth_operators_page()
    return render_template("admin/auth/operators.html", page=page)


# -----------------
# Audit/Reports
# -----------------
