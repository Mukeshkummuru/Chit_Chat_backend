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
            print(f"Received data from {phone_number}: {data}")
            message_data = json.loads(data)

            # Handle different message types
            if message_data.get("type") == "message":
                receiver = message_data.get("to")
                client_temp_id = message_data.get("client_temp_id")
                message_id = f"{phone_number}_{receiver}_{datetime.now(timezone.utc).timestamp()}"

                # Create message object
                msg_obj = {
                    "_id": message_id,
                    "from": phone_number,
                    "to": receiver,
                    "message": message_data.get("message"),
                    "time": datetime.now(timezone.utc).isoformat(),
                    "status": "sent",  # Start with 'sent'
                    "delivered_at": None,
                    "read_at": None
                }
                
                print(f"Saving chat message: {msg_obj}")
                chats_collection.insert_one(msg_obj)

                # Send FCM notification
                try:
                    sender = db["users"].find_one({"phone_number": phone_number})
                    send_fcm_notification(
                        to_phone=receiver,
                        sender_username=sender["username"] if sender else phone_number,
                        message_text=message_data.get("message")
                    )
                except Exception as e:
                    print(f"FCM notification error: {e}")

                # Update unread count for receiver
                chat_meta_collection.update_one(
                    {"user": receiver, "friend": phone_number},
                    {"$inc": {"unread": 1}},
                    upsert=True
                )

                # CRITICAL FIX: Always send delivery receipt to sender first
                print(f"Sending initial delivery receipt to sender: {phone_number}")
                initial_receipt = {
                    "type": "delivery_receipt",
                    "message_id": message_id,
                    "status": "sent",
                    "client_temp_id": client_temp_id
                }
                await websocket.send_text(json.dumps(initial_receipt))

                # Check if receiver is online
                if receiver in active_connections:
                    print(f"Receiver {receiver} is online, updating status to delivered")
                    
                    # Update message status to delivered in database
                    chats_collection.update_one(
                        {"_id": message_id},
                        {
                            "$set": {
                                "status": "delivered",
                                "delivered_at": datetime.now(timezone.utc).isoformat()
                            }
                        }
                    )
                    
                    # Send message to receiver
                    receiver_message = {
                        "type": "message",
                        "from": phone_number,
                        "to": receiver,
                        "message": message_data.get("message"),
                        "message_id": message_id,
                        "time": msg_obj["time"],
                        "client_temp_id": client_temp_id                      
                    }
                    await active_connections[receiver].send_text(json.dumps(receiver_message))
                    
                    # Echo the message event to the sender (for real-time UI update)
                    if phone_number in active_connections:
                        await active_connections[phone_number].send_text(json.dumps(receiver_message))

                    # Send updated delivery receipt to sender (delivered)
                    delivered_receipt = {
                        "type": "delivery_receipt",
                        "message_id": message_id,
                        "status": "delivered",
                        "client_temp_id": client_temp_id
                    }
                    print(f"Sending delivered receipt to sender: {phone_number}")
                    await websocket.send_text(json.dumps(delivered_receipt))

                # Send unread update to receiver (if online)
                await send_unread_update(receiver)

            # Handle read receipts
            elif message_data.get("type") == "read_receipt":
                message_id = message_data.get("message_id")
                sender_phone = message_data.get("sender")

                print(f"Processing read receipt for message: {message_id} from {phone_number}")

                # Update message status to read in database
                update_result = chats_collection.update_one(
                    {"_id": message_id, "from": sender_phone, "to": phone_number},
                    {
                        "$set": {
                            "status": "read",
                            "read_at": datetime.now(timezone.utc).isoformat()
                        }
                    }
                )
                
                print(f"Read receipt update result: modified {update_result.modified_count} documents")

                # Send read receipt back to original sender if they're online
                if sender_phone in active_connections:
                    read_receipt_response = {
                        "type": "read_receipt",
                        "message_id": message_id,
                        "status": "read"
                    }
                    print(f"Sending read receipt to original sender: {sender_phone}")
                    await active_connections[sender_phone].send_text(json.dumps(read_receipt_response))

            # Handle typing indicators
            elif message_data.get("type") == "typing":
                receiver = message_data.get("to")
                is_typing = message_data.get("is_typing", False)

                print(f"Typing indicator: {phone_number} -> {receiver}, typing: {is_typing}")

                if receiver in active_connections:
                    typing_message = {
                        "type": "typing",
                        "from": phone_number,
                        "to": receiver,
                        "is_typing": is_typing
                    }
                    await active_connections[receiver].send_text(json.dumps(typing_message))

    except WebSocketDisconnect:
        print(f"WebSocket disconnected: {phone_number}")
        set_user_offline(phone_number)
        if phone_number in active_connections:
            del active_connections[phone_number]
    except Exception as e:
        print(f"WebSocket error for {phone_number}: {e}")
        if phone_number in active_connections:
            del active_connections[phone_number]

# Add a REST endpoint to fetch chat history
@router.get("/history/{user1}/{user2}")
async def get_chat_history(
    user1: str,
    user2: str,
    limit: int = Query(50, ge=1, le=100),
    before: Optional[str] = None
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
    # Reset unread count
    chat_meta_collection.update_one(
        {"user": user, "friend": friend},
        {"$set": {"unread": 0}},
        upsert=True
    )

    # Get all unread messages from friend to user
    unread_messages = list(chats_collection.find({
        "from": friend,
        "to": user,
        "status": {"$in": ["sent", "delivered"]}  # Messages that haven't been read yet
    }))

    print(f"Found {len(unread_messages)} unread messages to mark as read")

    # Update all unread messages to read status
    if unread_messages:
        message_ids = [msg["_id"] for msg in unread_messages]
        update_result = chats_collection.update_many(
            {"_id": {"$in": message_ids}},
            {
                "$set": {
                    "status": "read",
                    "read_at": datetime.now(timezone.utc).isoformat()
                }
            }
        )
        print(f"Updated {update_result.modified_count} messages to read status")

        # Send read receipts for all these messages if friend is online
        if friend in active_connections:
            for msg in unread_messages:
                read_receipt = {
                    "type": "read_receipt",
                    "message_id": str(msg["_id"]),
                    "status": "read"
                }
                await active_connections[friend].send_text(json.dumps(read_receipt))
                print(f"Sent read receipt for message {msg['_id']} to {friend}")

    # Send unread updates to both users
    await send_unread_update(user)
    await send_unread_update(friend)

    return {"message": f"Unread count reset, {len(unread_messages)} messages marked as read"}

@router.delete("/delete_chat/{user}/{friend}")
async def delete_chat(user: str, friend: str):
    # Delete all chat messages between users
    delete_result = chats_collection.delete_many({
        "$or": [
            {"from": user, "to": friend},
            {"from": friend, "to": user}
        ]
    })
    
    # Delete chat metadata
    chat_meta_collection.delete_many({
        "$or": [
            {"user": user, "friend": friend},
            {"user": friend, "friend": user}
        ]
    })
    
    print(f"Deleted {delete_result.deleted_count} messages between {user} and {friend}")
    return {"message": f"Chat deleted, {delete_result.deleted_count} messages removed"}