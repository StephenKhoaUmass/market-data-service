from fastapi import FastAPI
from app.api.routes import router

app = FastAPI(
    title="Market Data Service",
    version="1.0.0"
)

app.include_router(router)
