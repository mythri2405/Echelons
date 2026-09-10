from app.routes.history import router as history_router
from app.supabase_client import supabase
from app.routes.hazard import router as hazard_router
from fastapi import FastAPI
from app.routes.detection import router as detection_router
from app.routes import stats
from app.routes import rag


app = FastAPI(
    title="deepEcho",
    description="AI-powered underwater sonar detection system",
    version="1.0.0"
)


@app.get("/")
def home():
    return {
        "message": "deepEcho backend is running"
    }

@app.get("/test-supabase")
def test_supabase():
    response = supabase.table("scans").select("*").limit(1).execute()

    return {
        "message": "Supabase connection working",
        "data": response.data
    }


app.include_router(detection_router)
app.include_router(history_router)
app.include_router(hazard_router)
app.include_router(stats.router)
app.include_router(rag.router)