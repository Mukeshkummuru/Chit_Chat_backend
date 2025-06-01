from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from models import update_user_profile, get_current_user, users_collection, is_user_online
from firebase_utils import upload_image_to_firebase
from schema import ProfileUpdateResponse, UserResponse

router = APIRouter()

@router.post("/update/", response_model=ProfileUpdateResponse)
async def update_profile(
    username: str = Form(...),
    bio: str = Form(...),
    image: UploadFile = File(None),
    email: str = Form(...),
    user: dict = Depends(get_current_user),  # <-- Use JWT auth
):
    phone_number = user["phone_number"]

    update_data = {
        "bio": bio,
        "email": email,
    }

    last_change_str = user.get("last_username_change")
    if last_change_str:
        last_change = datetime.fromisoformat(last_change_str)
        if (datetime.now() - last_change) < timedelta(days=15):
            # Do NOT allow username change
            update_data["username"] = user["username"]
        else:
            update_data["username"] = username
            update_data["last_username_change"] = datetime.now().isoformat()
    else:
        # If never changed before
        update_data["username"] = username
        update_data["last_username_change"] = datetime.now().isoformat()

    if image:
        content = await image.read()
        if image.filename and "." in image.filename:
            ext = image.filename.split(".")[-1]
        else:
            ext = ""
        image_url = upload_image_to_firebase(content, ext)
        update_data["profile_image_url"] = image_url

    updated_user = update_user_profile(phone_number, update_data)
    return {
        "message": "Profile updated successfully",
        "user": updated_user
    }

@router.get("/me/", response_model=UserResponse)
async def get_my_profile(user: dict = Depends(get_current_user)):
    user.setdefault("email", "")
    user.setdefault("bio", "")
    user.setdefault("profile_image_url", "")
    user.setdefault("friends", [])  # <-- Add this line
    return user

@router.get("/user/{phone_number}/")
async def get_user_by_phone(phone_number: str):
    user = users_collection.find_one({"phone_number": phone_number})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user["_id"] = str(user["_id"])
    user.setdefault("email", "")
    user.setdefault("bio", "")
    user.setdefault("profile_image_url", "")
    user.setdefault("username", "")
    return user

@router.get("/online_status/{phone_number}")
async def online_status(phone_number: str):
    return {"online": is_user_online(phone_number)}