import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from urllib.parse import quote_plus

password = quote_plus(os.getenv('DB_PASSWORD', 'P@ssword123'))
# 🔧 Replace with your real DB details
DATABASE_URL = f"mysql+mysqldb://root:{password}@localhost/etf_portal"

# Create engine and session
engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = scoped_session(sessionmaker(bind=engine))

# Optional: to create tables if not already created
# def create_tables():
#     Base.metadata.create_all(bind=engine)

# Usage:
# session = SessionLocal()
