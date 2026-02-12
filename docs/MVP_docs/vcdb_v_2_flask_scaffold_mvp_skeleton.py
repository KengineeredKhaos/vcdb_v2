# Directory layout (copy into your repo)
#
# vcdb/
# ├─ manage_vcdb.py
# ├─ config.py
# ├─ requirements.txt
# ├─ app/
# │  ├─ __init__.py
# │  ├─ extensions.py
# │  └─ v2/
# │     ├─ __init__.py
# │     ├─ render.py
# │     ├─ shared/
# │     │  ├─ __init__.py
# │     │  ├─ utils.py
# │     │  └─ security.py
# │     ├─ services/
# │     │  └─ docs_library.py
# │     ├─ customer/
# │     │  ├─ __init__.py
# │     │  ├─ routes.py
# │     │  └─ templates/
# │     │     └─ customer/
# │     │        └─ hello.html
# │     ├─ templates/
# │     │  ├─ layouts/
# │     │  │  └─ base.html
# │     │  └─ components/
# │     │     └─ macros.html
# │     └─ static/
# │        ├─ css/
# │        │  └─ v2.css
# │        └─ images/
# └─ alembic/  (created after `flask db init`)

########################################
# requirements.txt
########################################
Flask>=3.0
Flask-SQLAlchemy>=3.1
Flask-Migrate>=4.0
Flask-Login>=0.6
python-dotenv>=1.0
ulid-py>=1.1

########################################
# manage_vcdb.py — dev entrypoint
########################################
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True)

########################################
# config.py — env-driven config
########################################
import os

class BaseConfig:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-not-secret")
    SQLALCHEMY_DATABASE_URI = os.environ.get("VCDB_DB", "sqlite:///var/app-instance/dev.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    VCDB_TIMEZONE = os.environ.get("VCDB_TIMEZONE", "America/Los_Angeles")
    VCDB_ARCHIVE = os.environ.get("VCDB_ARCHIVE", "/tmp/vcdb-archive")

class DevConfig(BaseConfig):
    ENV = "development"

class ProdConfig(BaseConfig):
    ENV = "production"

########################################
# app/__init__.py — app factory, strict Jinja, bp register
########################################
from flask import Flask
from jinja2 import StrictUndefined
from .extensions import db, migrate, login_manager
from .v2 import create_v2_blueprint


def create_app(config_object="config.DevConfig"):
    app = Flask(__name__, template_folder=None, static_folder=None)
    app.config.from_object(config_object)

    # Strict Jinja across the app
    app.jinja_env.undefined = StrictUndefined

    # Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)

    # V2 blueprint (slice-first)
    v2_bp = create_v2_blueprint()
    app.register_blueprint(v2_bp, url_prefix="/v2")

    # Simple root to prove it works
    @app.get("/")
    def index():
        from flask import redirect, url_for
        return redirect(url_for("v2.customer.hello"))

    return app

########################################
# app/extensions.py — keep extensions in one place
########################################
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager


db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()

########################################
# app/v2/__init__.py — v2 blueprint + renderer hook
########################################
from flask import Blueprint
from .render import render_v2_template


def create_v2_blueprint() -> Blueprint:
    bp = Blueprint(
        "v2",
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    # Expose renderer for slices to import
    bp.render_v2_template = render_v2_template

    # Register sub-blueprints here
    from .customer import bp as customer_bp
    bp.register_blueprint(customer_bp, url_prefix="/customer")

    return bp

########################################
# app/v2/render.py — strict renderer for v2 templates
########################################
from flask import current_app, render_template


def render_v2_template(template_name: str, **context):
    """
    Wrapper to emphasize we’re rendering under v2’s StrictUndefined env.
    (StrictUndefined is set at the app level.)
    """
    return render_template(template_name, **context)

########################################
# app/v2/shared/__init__.py
########################################
# (intentionally empty)

########################################
# app/v2/shared/utils.py — ULID, time, idempotent log_event stub
########################################
from datetime import datetime, timezone
import ulid


def new_ulid() -> str:
    return str(ulid.new())


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")

# NOTE: Replace with real SQLAlchemy model later; this is just a façade
from flask import current_app
from ..render import render_v2_template  # unused here but keeps import paths warm


def log_event(envelope: dict) -> None:
    """Stub for idempotent insert into log_events.
    Real implementation will use db.session + UNIQUE(request_id).
    """
    current_app.logger.info({"event": envelope})

########################################
# app/v2/shared/security.py — simple role gate (placeholder)
########################################
from functools import wraps
from flask import abort


def roles_required(*role_names):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # TODO: integrate Flask-Login & real roles
            # For now, allow everything (dev).
            return fn(*args, **kwargs)
        return wrapper
    return decorator

########################################
# app/v2/services/docs_library.py — placeholder service
########################################
from pathlib import Path
from flask import current_app


def list_docs(root: Path) -> list[dict]:
    root = Path(root)
    items = []
    for p in sorted(root.glob("**/*")):
        if p.is_file():
            items.append({"name": p.name, "path": str(p)})
    return items

########################################
# app/v2/customer/__init__.py — slice-local blueprint
########################################
from flask import Blueprint

bp = Blueprint("customer", __name__, template_folder="templates", static_folder=None)

from . import routes  # noqa: E402  (register routes)

########################################
# app/v2/customer/routes.py — sample route using v2 renderer
########################################
from flask import current_app
from .. import render_v2_template
from . import bp


@bp.get("/hello")
def hello():
    current_app.logger.info("customer.hello")
    return render_v2_template("customer/hello.html", title="VCDB v2 Hello")

########################################
# app/v2/customer/templates/customer/hello.html
########################################
{% extends "layouts/base.html" %}
{% block content %}
  <div class="container">
    <h1 class="mt-4">{{ title }}</h1>
    <p>Scaffold is alive. This is the Customer slice.</p>
    <p><a href="/v2/docs/">Docs Library (stub)</a></p>
  </div>
{% endblock %}

########################################
# app/v2/templates/layouts/base.html — minimal base
########################################
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% if title %}{{ title }} — {% endif %}VCDB v2</title>
    <link rel="stylesheet" href="{{ url_for('v2.static', filename='css/v2.css') }}">
  </head>
  <body>
    <main>
      {% with messages = get_flashed_messages(with_categories=true) %}
        {% if messages %}
          <ul class="flashes">
            {% for category, message in messages %}
              <li class="flash {{ category }}">{{ message }}</li>
            {% endfor %}
          </ul>
        {% endif %}
      {% endwith %}
      {% block content %}{% endblock %}
    </main>
  </body>
</html>

########################################
# app/v2/templates/components/macros.html — placeholder
########################################
{% macro field_errors(errors) %}
  {% if errors %}
    <ul class="errors">
      {% for e in errors %}<li>{{ e }}</li>{% endfor %}
    </ul>
  {% endif %}
{% endmacro %}

########################################
# app/v2/static/css/v2.css — tiny style
########################################
body { font-family: system-ui, sans-serif; margin: 0; padding: 0; }
main { padding: 1rem 1.5rem; }
.flashes { list-style: none; padding: 0; }
.flash { padding: .5rem .75rem; margin: .25rem 0; border-radius: .25rem; background: #eee; }
