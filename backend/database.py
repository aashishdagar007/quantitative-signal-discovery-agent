import sqlalchemy as sa
from sqlalchemy import Table, Column, Integer, String, Boolean, MetaData, create_engine, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "postgresql://trading_user:trading_pass@localhost:5432/trading_db"

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="user")
    is_active = Column(Boolean, default=True)
    
    positions = relationship("Position", back_populates="owner")

class Position(Base):
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String, nullable=False)
    asset_class = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    entry_price = Column(float, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"))
    
    owner = relationship("User", back_populates="positions")

metadata = MetaData()

def create_db_and_tables():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_user_by_username(username: str):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).first()
        return user
    finally:
        db.close()

def authenticate_user(username: str, password: str):
    db = SessionLocal()
    try:
        user = get_user_by_username(username)
        if not user:
            return False
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes="bcrypt", deprecated="oauth2")
        if pwd_context.verify(password, user.hashed_password):
            return user
        return False
    finally:
        db.close()

ADMIN_USERNAME = "Lalit"

def seed_default_admin(username: str = ADMIN_USERNAME, password: str = "admin123", role: str = "admin"):
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if not existing:
            from passlib.context import CryptContext
            pwd_context = CryptContext(schemes="bcrypt", deprecated="oauth2")
            hashed_pw = pwd_context.hash(password)
            new_user = User(username=username, email=f"{username}@trading.local", hashed_password=hashed_pw, role=role)
            db.add(new_user)
            db.commit()
            print(f"Default admin user '{username}' seeded successfully")
        else:
            print(f"Admin user '{username}' already exists")
    finally:
        db.close()