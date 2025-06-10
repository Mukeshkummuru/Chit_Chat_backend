from datetime import datetime, timezone
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Dict, Optional
import json
from models import db
from jose import jwt, JWTError
from fcm_utils import send_fcm_notification
from models import set_user_online, set_user_offline, chats_collection

SECRET_KEY = "your_secret_key"
ALGORITHM = "HS256"

router = APIRouter()

active_connections: Dict[str, WebSocket] = {}
chats_collection = db["chats"]
chat_meta_collection = db["chat_meta"]

async def send_unread_update(user_phone):
    user_doc = db["users"].find_one({"phone_number": user_phone})
    if not user_doc:
        return
    friends = user_doc.get("friends", [])
    summary = {}
    for friend in friends:
        meta = chat_meta_collection.find_one({"user": user_phone, "friend": friend}) or {}
        unread = meta.get("unread", 0)
        # Get last message and time
        last_msg_doc = chats_collection.find_one(
            {"$or": [
                {"from": user_phone, "to": friend},
                {"from": friend, "to": user_phone}
            ]},
            sort=[("time", -1)]
        )
        last_message = last_msg_doc["message"] if last_msg_doc else ""
        last_message_time = last_msg_doc["time"] if last_msg_doc else ""
        summary[friend] = {
            "unread": unread,
            "last_message": last_message,
            "last_message_time": last_message_time
        }
    if user_phone in active_connections:
        await active_connections[user_phone].send_text(json.dumps({
            "type": "friends_update",
            "summary": summary
        }))
        
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
            message_data = json.loads(data)

            # Handle different message types
            if message_data.get("type") == "message":
                receiver = message_data.get("to")
                message_id = f"{phone_number}_{receiver}_{datetime.now(timezone.utc).timestamp()}"

                msg_obj = {
                    "_id": message_id,
                    "from": phone_number,
                    "to": receiver,
                    "message": message_data.get("message"),
                    "time": datetime.now(timezone.utc).isoformat(),
                    "status": "sent",
                    "delivered_at": None,
                    "read_at": None
                }
                print(f"Saving chat: {msg_obj}")
                chats_collection.insert_one(msg_obj)

                sender = db["users"].find_one({"phone_number": phone_number})
                send_fcm_notification(
                    to_phone=receiver,
                    sender_username=sender["username"] if sender else phone_number,
                    message_text=message_data.get("message")
                )

                chat_meta_collection.update_one(
                    {"user": receiver, "friend": phone_number},
                    {"$inc": {"unread": 1}},
                    upsert=True
                )

                # Send unread update to receiver
                await send_unread_update(receiver)

                if receiver in active_connections:
                    # Update message status to delivered
                    chats_collection.update_one(
                        {"_id": message_id},
                        {
                            "$set": {
                                "status": "delivered",
                                "delivered_at": datetime.now(timezone.utc).isoformat()
                            }
                        }
                    )
                    # Relay to receiver if online
                    await active_connections[receiver].send_text(json.dumps({
                        "type": "message",
                        "from": phone_number,
                        "message": message_data.get("message"),
                        "message_id": message_id,
                        "time": msg_obj["time"]
                    }))
                    # Send delivery receipt to sender (only once, after DB update)
                    delivery_receipt = {
                        "type": "delivery_receipt",
                        "message_id": message_id,
                        "status": "delivered"
                    }
                    await websocket.send_text(json.dumps(delivery_receipt))
                else:
                    # Send delivery receipt as 'sent'
                    delivery_receipt = {
                        "type": "delivery_receipt",
                        "message_id": message_id,
                        "status": "sent"
                    }
                    await websocket.send_text(json.dumps(delivery_receipt))

            # Handle read receipts
            elif message_data.get("type") == "read_receipt":
                message_id = message_data.get("message_id")
                sender_phone = message_data.get("sender")

                # Update message status to read
                chats_collection.update_one(
                    {"_id": message_id},
                    {
                        "$set": {
                            "status": "read",
                            "read_at": datetime.now(timezone.utc).isoformat()
                        }
                    }
                )

                # Send read receipt to sender if online
                if sender_phone in active_connections:
                    await active_connections[sender_phone].send_text(json.dumps({
                        "type": "read_receipt",
                        "message_id": message_id,
                        "status": "read"
                    }))

            # Handle typing indicators
            elif message_data.get("type") == "typing":
                receiver = message_data.get("to")
                is_typing = message_data.get("is_typing", False)

                if receiver in active_connections:
                    await active_connections[receiver].send_text(json.dumps({
                        "type": "typing",
                        "from": phone_number,
                        "is_typing": is_typing
                    }))

    except WebSocketDisconnect:
        set_user_offline(phone_number)
        print(f"WebSocket disconnected: {phone_number}")
        del active_connections[phone_number]

# Add a REST endpoint to fetch chat history
@router.get("/history/{user1}/{user2}")
async def get_chat_history(
    user1: str,
    user2: str,
    limit: int = Query(50, ge=1, le=100),
    before: Optional[str] = None  # ISO timestamp or ObjectId string
):
    query = {
        "$or": [
            {"from": user1, "to": user2},
            {"from": user2, "to": user1}
        ]
    }
    if before:
        query["time"] = {"$lt": before}
    messages = list(
        chats_collection.find(query)
        .sort("time", -1)
        .limit(limit)
    )
    messages.reverse()  # So the oldest is first
    return messages

@router.post("/reset_unread/{user}/{friend}")
async def reset_unread(user: str, friend: str):
    chat_meta_collection.update_one(
        {"user": user, "friend": friend},
        {"$set": {"unread": 0}},
        upsert=True
    )

    # Mark all unread messages from friend as read
    unread_messages = list(chats_collection.find({
        "from": friend,
        "to": user,
        "status": {"$ne": "read"}
    }))

    # Update messages to read status
    chats_collection.update_many(
        {"from": friend, "to": user, "status": {"$ne": "read"}},
        {
            "$set": {
                "status": "read",
                "read_at": datetime.now(timezone.utc).isoformat()
            }
        }
    )

    # Send read receipts for all unread messages
    if friend in active_connections:
        for msg in unread_messages:
            await active_connections[friend].send_text(json.dumps({
                "type": "read_receipt",
                "message_id": str(msg["_id"]),
                "status": "read"
            }))

    # Send unread update to user (the one who just read)
    await send_unread_update(user)
    # Optionally, also notify the friend
    await send_unread_update(friend)

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