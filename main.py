import os
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from requests.exceptions import RequestException
from database import db, create_document, get_documents

app = FastAPI(title="F1 API", description="Simple Formula 1 data API using Ergast + MongoDB for favorites")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ERGAST_BASE = "https://ergast.com/api/f1"

class FavoriteDriverIn(BaseModel):
    driver_id: str
    code: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    nationality: str | None = None

class FavoriteConstructorIn(BaseModel):
    constructor_id: str
    name: str | None = None
    nationality: str | None = None

@app.get("/")
def read_root():
    return {"message": "F1 backend running"}

@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    return response

# External API helpers

def fetch_ergast(endpoint: str, params: dict | None = None):
    url = f"{ERGAST_BASE}/{endpoint}.json"
    try:
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Upstream error {r.status_code}")
        return r.json()
    except RequestException as e:
        # Surface a clear 503 so the frontend can show an offline state
        raise HTTPException(status_code=503, detail="External data source unavailable: ergast.com") from e

# Helper: offline fallback for seasons

def offline_seasons(limit: int = 80, offset: int = 0):
    current_year = datetime.utcnow().year
    start_year = 1950
    seasons_list = []
    for y in range(start_year, current_year + 1):
        seasons_list.append({
            "season": str(y),
            "url": f"https://en.wikipedia.org/wiki/{y}_Formula_One_World_Championship"
        })
    # Apply paging similar to Ergast
    paged = seasons_list[offset: offset + limit]
    return {"count": len(paged), "items": paged, "offline": True}

# Public F1 data endpoints (read-only from Ergast)

@app.get("/api/seasons")
def list_seasons(limit: int = 80, offset: int = 0):
    try:
        data = fetch_ergast("seasons", {"limit": limit, "offset": offset})
        seasons = data.get("MRData", {}).get("SeasonTable", {}).get("Seasons", [])
        return {"count": len(seasons), "items": seasons}
    except HTTPException as e:
        if e.status_code == 503:
            return offline_seasons(limit=limit, offset=offset)
        raise

@app.get("/api/{season}/drivers")
def list_drivers(season: int):
    try:
        data = fetch_ergast(f"{season}/drivers")
        drivers = data.get("MRData", {}).get("DriverTable", {}).get("Drivers", [])
        return {"season": season, "count": len(drivers), "items": drivers}
    except HTTPException as e:
        if e.status_code == 503:
            return {"season": season, "count": 0, "items": [], "offline": True}
        raise

@app.get("/api/{season}/constructors")
def list_constructors(season: int):
    try:
        data = fetch_ergast(f"{season}/constructors")
        constructors = data.get("MRData", {}).get("ConstructorTable", {}).get("Constructors", [])
        return {"season": season, "count": len(constructors), "items": constructors}
    except HTTPException as e:
        if e.status_code == 503:
            return {"season": season, "count": 0, "items": [], "offline": True}
        raise

@app.get("/api/{season}/races")
def list_races(season: int):
    try:
        data = fetch_ergast(f"{season}.json")
        races = data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        return {"season": season, "count": len(races), "items": races}
    except HTTPException as e:
        if e.status_code == 503:
            return {"season": season, "count": 0, "items": [], "offline": True}
        raise

@app.get("/api/{season}/{round}/results")
def race_results(season: int, round: int):
    try:
        data = fetch_ergast(f"{season}/{round}/results")
        races = data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        results = races[0]["Results"] if races else []
        return {"season": season, "round": round, "count": len(results), "items": results}
    except HTTPException as e:
        if e.status_code == 503:
            return {"season": season, "round": round, "count": 0, "items": [], "offline": True}
        raise

# Favorites using MongoDB for persistence

@app.post("/api/favorites/drivers")
def add_favorite_driver(payload: FavoriteDriverIn):
    inserted_id = create_document("favoritedriver", payload)
    return {"id": inserted_id}

@app.get("/api/favorites/drivers")
def get_favorite_drivers():
    docs = get_documents("favoritedriver")
    # Convert ObjectId to string if present
    for d in docs:
        if "_id" in d:
            d["_id"] = str(d["_id"])
    return {"count": len(docs), "items": docs}

@app.post("/api/favorites/constructors")
def add_favorite_constructor(payload: FavoriteConstructorIn):
    inserted_id = create_document("favoriteconstructor", payload)
    return {"id": inserted_id}

@app.get("/api/favorites/constructors")
def get_favorite_constructors():
    docs = get_documents("favoriteconstructor")
    for d in docs:
        if "_id" in d:
            d["_id"] = str(d["_id"])
    return {"count": len(docs), "items": docs}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
