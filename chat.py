from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Dict
import json
from models import db
from jose import jwt, JWTError
from fcm_utils import send_fcm_notification
from models import set_user_online, set_user_offline

# Set these according to your project settings
SECRET_KEY = "your_secret_key"  
ALGORITHM = "HS256"             

router = APIRouter()

active_connections: Dict[str, WebSocket] = {}
chats_collection = db["chats"]

# NEW: Collection for unread counts and chat meta
chat_meta_collection = db["chat_meta"]   

@router.websocket("/ws/{phone_number}")
async def websocket_endpoint(
    websocket: WebSocket,
    phone_number: str,
    token: str = Query(None)
):
    print(f"WebSocket connect attempt: {phone_number} with token: {token}")
    # JWT validation
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_phone = payload.get("sub")
        print(f"Token subject: {user_phone}")
        if user_phone != phone_number:
            print("Token phone does not match path phone")
            await websocket.close(code=1008)
            return
    except JWTError as e:
        print(f"JWT error: {e}")
        await websocket.close(code=1008)
        return

    await websocket.accept()
    set_user_online(phone_number)
    active_connections[phone_number] = websocket
    print(f"WebSocket accepted: {phone_number}")
    try:
        while True:
            data = await websocket.receive_text()
            print(f"Received data: {data}")
            message = json.loads(data)
            receiver = message.get("to")
            msg_obj = {
                "from": phone_number,
                "to": receiver,
                "message": message.get("message"),
                "time": datetime.now(timezone.utc).isoformat()     
                
            }
            print(f"Saving chat: {msg_obj}")
            chats_collection.insert_one(msg_obj)

            sender = db["users"].find_one({"phone_number": phone_number})
            send_fcm_notification(
                to_phone=receiver,
                sender_username=sender["username"] if sender else phone_number,
                message_text=message.get("message")
            )
           
            chat_meta_collection.update_one(
                {"user": receiver, "friend": phone_number},
                {"$inc": {"unread": 1}},
                upsert=True
            )
            # Relay to receiver if online
            if receiver in active_connections:
                await active_connections[receiver].send_text(json.dumps({
                    "from": phone_number,
                    "message": message.get("message")
                }))
    except WebSocketDisconnect:
        set_user_offline(phone_number)
        print(f"WebSocket disconnected: {phone_number}")
        del active_connections[phone_number]

# Add a REST endpoint to fetch chat history
@router.get("/history/{user1}/{user2}")
async def get_chat_history(user1: str, user2: str):
    chats = list(chats_collection.find({
        "$or": [
            {"from": user1, "to": user2},
            {"from": user2, "to": user1}
        ]
    }))
    for c in chats:
        c["_id"] = str(c["_id"])
    return chats

# NEW: Endpoint for last message and unread count
@router.get("/last_message/{user}/{friend}")
async def last_message(user: str, friend: str):
    last = chats_collection.find_one(
        {"$or": [
            {"from": user, "to": friend},
            {"from": friend, "to": user}
        ]},
        sort=[("_id", -1)]
    )
    meta = chat_meta_collection.find_one({"user": user, "friend": friend}) or {}
    return {
        "message": last["message"] if last else "",
        "unread": meta.get("unread", 0),
        "time": last["time"] if last and "time" in last else ""
    }

# NEW: Endpoint to reset unread count when chat is opened
@router.post("/reset_unread/{user}/{friend}")
async def reset_unread(user: str, friend: str):
    chat_meta_collection.update_one(
        {"user": user, "friend": friend},
        {"$set": {"unread": 0}},
        upsert=True
    )
    return {"message": "Unread count reset"}

@router.delete("/delete_chat/{user}/{friend}")
async def delete_chat(user: str, friend: str):
    chats_collection.delete_many({
        "$or": [
            {"from": user, "to": friend},
            {"from": friend, "to": user}
        ]
    })
    chat_meta_collection.delete_many({
        "$or": [
            {"user": user, "friend": friend},
            {"user": friend, "friend": user}
        ]
    })
    return {"message": "Chat deleted"}