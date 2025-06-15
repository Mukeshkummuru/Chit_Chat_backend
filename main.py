from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from auth import router as auth_router
from profile_routes import router as profile_router
from chat import router as chat_router
from friend_requests import router as friend_requests_router

app = FastAPI()

""" @app.middleware("http")
async def log_requests(request, call_next):
    print(f"Request: {request.method} {request.url}")
    response = await call_next(request)
    return response """

@app.get("/")
def read_root():
    return {"message": "Chit Chat API is running!"}
    
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(profile_router, prefix="/profile", tags=["Profile"])
app.include_router(chat_router, prefix="/chat", tags=["Chat"])
app.include_router(friend_requests_router, prefix="/friends", tags=["Friends"])
 