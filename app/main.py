from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth as auth_router


app = FastAPI(title="JobOS API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check() -> dict:
    return {"status": "ok"}


app.include_router(auth_router.router)
