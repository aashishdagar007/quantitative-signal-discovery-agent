from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
from jose import JWTError, jwt
from passlib.context import CryptContext
import database
from database import User, create_db_and_tables, seed_default_admin, get_user_by_username

app = FastAPI(title="AI Trading System Backend")

SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(schemes="bcrypt", deprecated="oauth2")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    role: str = "user"

class Token(BaseModel):
    access_token: str
    token_type: str

class UserInDB(BaseModel):
    username: str
    email: str
    hashed_password: str
    role: str
    is_active: bool = True

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_hash_password(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    import datetime
    to_encode = data.copy()
    expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(db=database.SessionLocal, token: str = Depends(oauth2_scheme)):
    from jose import JWTError
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    
    user = get_user_by_username(db, username=username)
    if user is None:
        raise credentials_exception
    return user

def get_current_active_user(current_user = Depends(get_current_user)):
    if current_user.is_active:
        return current_user
    raise HTTPException(status_code=400, detail="Inactive user")

ADMIN_USERNAME = "Lalit"

@app.on_event("startup")
async def startup():
    create_db_and_tables()
    seed_default_admin(username=ADMIN_USERNAME, password="admin123", role="admin")

@app.get("/")
async def root():
    return {"message": "AI Trading System Backend is running"}

@app.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(username=form_data.username, password=form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/users/me")
async def read_users_me(current_user = Depends(get_current_active_user)):
    return {"username": current_user.username, "email": current_user.email, "role": current_user.role}

def check_role(allowed_roles: list):
    def dependency(current_user = Depends(get_current_active_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions"
            )
        return current_user
    return dependency

@app.get("/admin/dashboard")
async def admin_dashboard(current_user = Depends(check_role(["admin"]))):
    return {"message": "Admin dashboard", "user": current_user.username}