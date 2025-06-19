import os
os.environ["DATABASE_URL"] = "postgresql://khoaho:postgres@localhost:6543/market"

from app.models.db import Base, engine
from app.models import market_data

print("Creating tables...")
Base.metadata.create_all(bind=engine)
print("Done.")

