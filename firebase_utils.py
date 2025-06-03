import firebase_admin
from firebase_admin import credentials, storage
import uuid
import os
import json

# Write the JSON string from environment to a temp file
cred_path = "/tmp/firebase_admin_sdk.json"
firebase_json = os.getenv("FIREBASE_CREDENTIALS_JSON")

# Create the file only if it doesn't already exist
if firebase_json and not os.path.exists(cred_path):
    with open(cred_path, "w") as f:
        f.write(firebase_json)

# Initialize Firebase app
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
