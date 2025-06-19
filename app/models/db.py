from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
import os

# You can configure this using dotenv or a config file later
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://khoaho:postgres@localhost:6543/market"
)

engine = create_engine(DATABASE_URL)
SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()

def get_db_session():
    """Dependency-style generator for session usage in FastAPI"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
