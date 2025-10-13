# In app/__init__.py (inside create_app, after DB init and BP registrations)
from app.extensions import event_bus
from app.slices.transactions import services as tx_services

event_bus.register_sink(tx_services.log_event)
# Now all event_bus.emit(...) calls persist via Transactions slice.
