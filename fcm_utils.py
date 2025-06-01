import firebase_admin
from firebase_admin import messaging
from models import db
from firebase_utils import cred

# Only initialize if not already initialized
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

def send_fcm_notification(to_phone, sender_username, message_text):
    user = db["users"].find_one({"phone_number": to_phone})
    if not user or "fcm_token" not in user:
        print("No FCM token for user", to_phone)
        return
    message = messaging.Message(
        notification=messaging.Notification(
            title=f"New message from {sender_username}",
            body=message_text,
        ),
        token=user["fcm_token"],
    )
    response = messaging.send(message)
    print("Sent FCM notification:", response)