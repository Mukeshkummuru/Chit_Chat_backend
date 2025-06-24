from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from models import update_user_profile, get_current_user, users_collection, is_user_online
from firebase_utils import upload_image_to_firebase
from schema import ProfileUpdateResponse, UserResponse
from models import chats_collection
from fastapi import Body

router = APIRouter()

@router.get("/friends_summary/")
async def friends_summary(user: dict = Depends(get_current_user)):
    my_phone = user["phone_number"]
    user_doc = users_collection.find_one({"phone_number": my_phone})
    if not user_doc:
        raise HTTPException(status_code=404, detail="User not found")
    friends = user_doc.get("friends", [])
    result = []
    for friend in friends:
        friend_user = users_collection.find_one({"phone_number": friend}) or {}
        last_msg = chats_collection.find_one(
            {"$or": [
                {"from": my_phone, "to": friend},
                {"from": friend, "to": my_phone}
            ]},
            sort=[("time", -1)]
        )

        unread_count = chats_collection.count_documents({
        "from": friend,
        "to": my_phone,
        "status": {"$in": ["sent", "delivered"]}
        })

        result.append({
            "phone_number": friend,
            "username": friend_user.get("username", ""),
            "profile_image_url": friend_user.get("profile_image_url", ""),
            "bio": friend_user.get("bio", ""),
            "email": friend_user.get("email", ""),
            "last_message": last_msg["message"] if last_msg else "",
            "last_message_time": last_msg["time"] if last_msg else "",
            "last_message_status": last_msg["status"] if last_msg else "",
            "unread": unread_count,
        })
    return result

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

@router.post("/update_fcm_token/")
async def update_fcm_token(
    fcm_token: str = Body(..., embed=True),
    user: dict = Depends(get_current_user)
):
    users_collection.update_one(
        {"phone_number": user["phone_number"]},
        {"$set": {"fcm_token": fcm_token}}
    )
    return {"message": "FCM token updated"}

@router.get("/online_status/{phone_number}")
async def online_status(phone_number: str):
    return {"online": is_user_online(phone_number)}