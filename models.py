import os
from pymongo import MongoClient, ReturnDocument
from dotenv import load_dotenv
from datetime import datetime, timedelta
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

load_dotenv()

client = MongoClient(os.getenv("MONGODB_URI"))
db = client["chat_app"]
users_collection = db["users"]
chats_collection = db["chats"]
presence_collection = db["presence"]
users_collection.update_many({"bio": {"$exists": False}}, {"$set": {"bio": ""}})
users_collection.update_many({"email": {"$exists": False}}, {"$set": {"email": ""}})
users_collection.update_many({"profile_image_url": {"$exists": False}}, {"$set": {"profile_image_url": ""}})

SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key")
ALGORITHM = "HS256"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login/")

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())

def register_user(user_data: dict):
    if users_collection.find_one({"phone_number": user_data["phone_number"]}):
        return False
    user_data["password"] = hash_password(user_data["password"])
    users_collection.insert_one(user_data)
    return True

def authenticate_user(phone_number: str, password: str):
    user = users_collection.find_one({"phone_number": phone_number})
    if user and verify_password(password, user["password"]):
        return user
    return None

def create_access_token(user: dict):
    expire = datetime.utcnow() + timedelta(days=30)
    return jwt.encode({"sub": user["phone_number"], "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def get_user_by_phone(phone_number):
    """ print(f"Looking for phone: {phone_number}") """
    user = users_collection.find_one({"phone_number": phone_number})
    if user:
        user["_id"] = str(user["_id"])
    return user

def update_user_profile(phone_number, update_data):
    user = users_collection.find_one_and_update(
        {"phone_number": phone_number},
        {"$set": update_data},
        return_document=ReturnDocument.AFTER
    )
    if user:
        user["_id"] = str(user["_id"])
    return user

def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        phone_number: str = payload.get("sub") # type: ignore
        if phone_number is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user_by_phone(phone_number)
    if user is None:
        raise credentials_exception
    return user

def set_user_online(phone_number: str):
    presence_collection.update_one(
        {"phone_number": phone_number},
        {"$set": {"online": True}},
        upsert=True
    )

def set_user_offline(phone_number: str):
    presence_collection.update_one(
        {"phone_number": phone_number},
        {"$set": {"online": False}},
        upsert=True
    )

def is_user_online(phone_number: str) -> bool:
    doc = presence_collection.find_one({"phone_number": phone_number})
    return bool(doc and doc.get("online", False))