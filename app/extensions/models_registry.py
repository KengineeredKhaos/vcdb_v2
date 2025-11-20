# Single place to import all slice models so Alembic sees them.
# DO NOT add any runtime logic here — imports only.
# Keep list alphabetized to avoid churn in diffs.

"""
# flake8: noqa
from app.slices.admin import models as _admin_models
from app.slices.attachments import models as _attachments_models
from app.slices.auth import models as _auth_models
from app.slices.calendar import models as _calendar_models
from app.slices.customers import models as _customers_models
from app.slices.entity import models as _entity_models
from app.slices.finance import models as _finance_models
from app.slices.governance import models as _governance_models
from app.slices.ledger import models as _ledger_models
from app.slices.logistics import models as _logistics_models
from app.slices.resources import models as _resources_models
from app.slices.sponsors import models as _sponsors_models

# ...add other slices as they come online
"""
