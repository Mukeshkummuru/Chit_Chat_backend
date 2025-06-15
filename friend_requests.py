from fastapi import APIRouter, Depends, HTTPException
from models import get_current_user, db
from schema import UserResponse

# --- Add these imports ---
import json
from chat import active_connections  # Import your active_connections from chat.py

router = APIRouter()

# Collection for friend requests
friend_requests_collection = db["friend_requests"]
users_collection = db["users"]

def ensure_user_fields(user):
    user.setdefault("email", "")
    user.setdefault("bio", "")
    user.setdefault("profile_image_url", "")
    return user

async def send_friends_update(phone_number):
    print(f"send_friends_update called for {phone_number}")
    if phone_number in active_connections:
        print(f"Sending friends update to {phone_number} (connection found)")
        await active_connections[phone_number].send_text(json.dumps({
            "type": "friends_update_trigger"
        }))
    else:
        print(f"No active connection for {phone_number}")
        

# --- WebSocket push for pending requests ---
async def send_pending_requests_update(phone_number):
    print(f"send_pending_requests_update called for {phone_number}")
    user_doc = users_collection.find_one({"phone_number": phone_number})
    if not user_doc:
        print(f"No user doc found for {phone_number}")
        return
    pending_requests = list(friend_requests_collection.find({"to": phone_number, "status": "pending"}))
    summary = {
        "pending_count": len(pending_requests),
        "pending_requests": [
            {
                "from": req["from"],
                "status": req["status"]
            } for req in pending_requests
        ]
    }
    if phone_number in active_connections:
        print(f"Sending pending requests update to {phone_number} (connection found)")
        await active_connections[phone_number].send_text(json.dumps({
            "type": "pending_requests_update",
            "summary": summary
        }))
    else:
        print(f"No active connection for {phone_number}")

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
    # --- Push update to recipient ---
    await send_pending_requests_update(to_phone)
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
    # --- Push update to both users ---
    await send_pending_requests_update(to_phone)
    await send_pending_requests_update(from_phone)
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
    # --- Optionally push update if you want to update requests/friends in UI ---
    await send_pending_requests_update(my_phone)
    await send_pending_requests_update(friend_phone)
    # --- Push friends update to both users ---
    await send_friends_update(my_phone)
    await send_friends_update(friend_phone)
    return {"message": "Unfriended"}

@router.get("/all_users_and_friends/")
async def all_users_and_friends(user: dict = Depends(get_current_user)):
    my_phone = user["phone_number"]
    all_users = list(users_collection.find({"phone_number": {"$ne": my_phone}}))
    friends = user.get("friends", [])
    pending_requests = list(friend_requests_collection.find({"to": my_phone, "status": "pending"}))
    # Build pending_requests with user info
    pending_requests_with_user = []
    for req in pending_requests:
        from_user = users_collection.find_one({"phone_number": req["from"]}) or {}
        pending_requests_with_user.append({
            "phone_number": req["from"],
            "username": from_user.get("username", ""),
            "bio": from_user.get("bio", ""),
            "profile_image_url": from_user.get("profile_image_url", ""),
        })
  
    sent_requests = list(friend_requests_collection.find({"from": my_phone, "status": "pending"}))
    sent_requests_phones = [req["to"] for req in sent_requests]
    
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
        "pending_requests": pending_requests_with_user,
        "sent_requests": sent_requests_phones,  
    }