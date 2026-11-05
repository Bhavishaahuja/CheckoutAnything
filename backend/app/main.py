from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app import mandates, orders, review
from backend.app.config import get_settings

app = FastAPI(title="Leash API")

# Vite dev server, plus wherever the frontend is deployed
allowed_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
frontend_origin = get_settings().frontend_origin
if frontend_origin:
    allowed_origins.append(frontend_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# mandates first since orders get checked against them
app.include_router(mandates.router)
app.include_router(orders.router)
app.include_router(review.router)


@app.get("/health")
def health():
    return {"status": "ok"}
