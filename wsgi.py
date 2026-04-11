import os

os.environ.setdefault("VCDB_ENV", "production")

from app import create_app
from config import ProdConfig

ProdConfig.validate()
application = create_app(config_object=ProdConfig)
