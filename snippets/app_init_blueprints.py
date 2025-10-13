# In app/__init__.py — within create_app():
from app.slices.calendar import bp as calendar_bp
from app.slices.customers import bp as customers_bp
from app.slices.governance import bp as governance_bp
from app.slices.inventory import bp as inventory_bp
from app.slices.resources import bp as resources_bp
from app.slices.sponsors import bp as sponsors_bp
from app.slices.transactions import bp as transactions_bp

app.register_blueprint(customers_bp)
app.register_blueprint(calendar_bp)
app.register_blueprint(governance_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(resources_bp)
app.register_blueprint(sponsors_bp)
app.register_blueprint(transactions_bp)

# optionally call util.boot.dump_routes(app)
