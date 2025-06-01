import firebase_admin
from firebase_admin import credentials, storage
import uuid
import os

cred_path = os.getenv("FIREBASE_ADMIN_SDK_PATH", "/etc/secrets/firebase_admin_sdk.json")
cred = credentials.Certificate(cred_path)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET")
    })

def upload_image_to_firebase(file_data: bytes, file_extension: str) -> str:
    bucket = storage.bucket()
    blob = bucket.blob(f"profile_images/{uuid.uuid4()}.{file_extension}")
    blob.upload_from_string(file_data, content_type=f"image/{file_extension}")
    blob.make_public()
    return blob.public_url