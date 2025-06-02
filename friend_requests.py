from fastapi import APIRouter, Depends, HTTPException
from models import get_current_user, db
from schema import UserResponse
 

router = APIRouter()

# Collection for friend requests
friend_requests_collection = db["friend_requests"]
users_collection = db["users"]

def ensure_user_fields(user):
    user.setdefault("email", "")
    user.setdefault("bio", "")
    user.setdefault("profile_image_url", "")
    return user

@router.get("/all_users/", response_model=list[UserResponse])
async def get_all_users(user: dict = Depends(get_current_user)):
    users = list(users_collection.find({"phone_number": {"$ne": user["phone_number"]}}))
    for u in users:
        u["_id"] = str(u["_id"])
        ensure_user_fields(u)
    return users

@router.post("/send_request/{to_phone}/")
async def send_friend_request(to_phone: str, user: dict = Depends(get_current_user)):
    from_phone = user["phone_number"]
    if from_phone == to_phone:
        raise HTTPException(status_code=400, detail="Cannot send request to yourself.")
    # Check if already sent
    if friend_requests_collection.find_one({"from": from_phone, "to": to_phone, "status": "pending"}):
        raise HTTPException(status_code=400, detail="Request already sent.")
    # Save the request
    friend_requests_collection.insert_one({
        "from": from_phone,
        "to": to_phone,
        "status": "pending"
    })
    return {"message": "Friend request sent"}

# Get pending requests for the current user
@router.get("/pending_requests/")
async def get_pending_requests(user: dict = Depends(get_current_user)):
    requests = list(friend_requests_collection.find({"to": user["phone_number"], "status": "pending"}))
    for r in requests:
        r["_id"] = str(r["_id"])
    return requests

# Accept a friend request
@router.post("/accept_request/{from_phone}/")
async def accept_friend_request(from_phone: str, user: dict = Depends(get_current_user)):
    to_phone = user["phone_number"]
    req = friend_requests_collection.find_one_and_update(
        {"from": from_phone, "to": to_phone, "status": "pending"},
        {"$set": {"status": "accepted"}}
    )
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    # Add each user to the other's friends list
    users_collection.update_one({"phone_number": from_phone}, {"$addToSet": {"friends": to_phone}})
    users_collection.update_one({"phone_number": to_phone}, {"$addToSet": {"friends": from_phone}})
    return {"message": "Friend request accepted"}

@router.post("/unfriend/{friend_phone}/")
async def unfriend(friend_phone: str, user: dict = Depends(get_current_user)):
    my_phone = user["phone_number"]
    print(f"Unfriending: {my_phone} <-> {friend_phone}")
    result1 = users_collection.update_one(
        {"phone_number": my_phone},
        {"$pull": {"friends": friend_phone}}
    )
    result2 = users_collection.update_one(
        {"phone_number": friend_phone},
        {"$pull": {"friends": my_phone}}
    )
    print(f"Update results: {result1.modified_count}, {result2.modified_count}")
    return {"message": "Unfriended"}

# Add to your backend (e.g., friends_routes.py)
@router.get("/all_users_and_friends/")
async def all_users_and_friends(user: dict = Depends(get_current_user)):
    my_phone = user["phone_number"]
    all_users = list(users_collection.find({"phone_number": {"$ne": my_phone}}))
    friends = user.get("friends", [])
    pending_requests = list(friend_requests_collection.find({"to": my_phone, "status": "pending"}))
    # Convert ObjectId to str for pending_requests
    for req in pending_requests:
        req["_id"] = str(req["_id"])
    return {
        "users": [
            {
                "phone_number": u["phone_number"],
                "username": u.get("username", ""),
                "profile_image_url": u.get("profile_image_url", ""),
                "bio": u.get("bio", ""),
            } for u in all_users
        ],
        "friends": friends,
        "pending_requests": pending_requests,
    }