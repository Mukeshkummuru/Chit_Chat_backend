from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from models import register_user, authenticate_user, create_access_token


router = APIRouter()

from pydantic import field_validator

class RegisterRequest(BaseModel):
    phone_number: str
    username: str
    password: str

    @field_validator('phone_number')
    def validate_phone(cls, v):
        v = v.strip().replace(" ", "").replace("-", "")
        if not v.startswith("+91"):
            if not v.isdigit() or len(v) != 10:
                raise ValueError("Phone number must be a valid 10-digit Indian number.")
            v = "+91" + v
        return v

class LoginRequest(BaseModel):
    phone_number: str
    password: str

@router.post("/register/")
async def register(data: RegisterRequest):
    user_data = data.model_dump()
    # Ensure all required fields exist, even if empty
    user_data.setdefault("email", "")
    user_data.setdefault("bio", "")
    user_data.setdefault("profile_image_url", "")
    if register_user(user_data):
        return {"message": "User registered successfully!"}
    raise HTTPException(status_code=400, detail="User already exists")


@router.post("/login/")
async def login(data: LoginRequest):
    user = authenticate_user(data.phone_number, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user)
    return {"access_token": token, "token_type": "bearer"}
