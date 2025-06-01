from pydantic import BaseModel, Field
from typing import List, Optional

class UserResponse(BaseModel):
    id: Optional[str] = Field(alias="_id")
    phone_number: str
    username: str
    email:str
    bio: Optional[str] = ""
    profile_image_url: Optional[str] = ""
    friends: Optional[List[str]] = [] 

    class Config:
        allow_population_by_field_name = True

class ProfileUpdateResponse(BaseModel):
    message: str
    user: UserResponse