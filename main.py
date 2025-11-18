import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document
from schemas import ParkingLot, ParkingSpot, Booking

try:
    from bson import ObjectId
except Exception:  # Fallback if bson not available for some reason
    ObjectId = None  # type: ignore

app = FastAPI(title="AI Parking API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"message": "AI Parking API is running"}


# Seed demo data for quick testing
@app.post("/seed")
def seed_demo_data():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    existing_lots = list(db["parkinglot"].find())
    if existing_lots:
        return {"status": "ok", "seeded": False}

    lot_id = create_document(
        "parkinglot",
        ParkingLot(
            name="Downtown Central",
            latitude=37.7749,
            longitude=-122.4194,
            address="123 Market St, San Francisco, CA",
            price_per_hour=5.0,
            total_spots=12,
        ),
    )

    # Create a mix of spots
    for i in range(1, 13):
        vtype = "car"
        if i in (3, 7):
            vtype = "ev"
        if i in (5,):
            vtype = "accessible"
        create_document(
            "parkingspot",
            ParkingSpot(lot_id=lot_id, spot_number=str(i), vehicle_type=vtype, is_occupied=False),
        )

    return {"status": "ok", "seeded": True, "lot_id": lot_id}


class LotWithAvailability(BaseModel):
    id: str
    name: str
    address: Optional[str]
    latitude: float
    longitude: float
    price_per_hour: float
    total_spots: int
    available_spots: int


@app.get("/lots", response_model=List[LotWithAvailability])
def list_lots():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    lots = list(db["parkinglot"].find())
    results: List[LotWithAvailability] = []
    for lot in lots:
        lot_id = str(lot.get("_id"))
        total = lot.get("total_spots", 0)
        occupied = db["parkingspot"].count_documents({"lot_id": lot_id, "is_occupied": True})
        available = max(total - occupied, 0)
        results.append(
            LotWithAvailability(
                id=lot_id,
                name=lot.get("name"),
                address=lot.get("address"),
                latitude=lot.get("latitude"),
                longitude=lot.get("longitude"),
                price_per_hour=lot.get("price_per_hour"),
                total_spots=total,
                available_spots=available,
            )
        )
    return results


class RecommendationRequest(BaseModel):
    lat: float
    lng: float
    vehicle_type: Optional[str] = None

class RecommendationResponse(BaseModel):
    lot_id: str
    lot_name: str
    spot_id: Optional[str]
    spot_number: Optional[str]
    reason: str


def haversine(lat1, lon1, lat2, lon2):
    from math import radians, sin, cos, sqrt, atan2
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


@app.post("/recommend", response_model=RecommendationResponse)
def recommend_parking(req: RecommendationRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    lots = list(db["parkinglot"].find())
    if not lots:
        raise HTTPException(status_code=404, detail="No parking lots available. Seed data first.")

    best = None
    best_score = float("inf")
    chosen_spot = None
    for lot in lots:
        lot_id = str(lot.get("_id"))
        spots = list(db["parkingspot"].find({"lot_id": lot_id, "is_occupied": False}))
        if req.vehicle_type:
            spots = [s for s in spots if s.get("vehicle_type") == req.vehicle_type]
        if not spots:
            continue
        dist = haversine(req.lat, req.lng, lot.get("latitude"), lot.get("longitude"))
        score = dist - 0.05 * len(spots)
        if score < best_score:
            best_score = score
            best = lot
            chosen_spot = spots[0]

    if best is None:
        raise HTTPException(status_code=404, detail="No suitable spots found")

    return RecommendationResponse(
        lot_id=str(best.get("_id")),
        lot_name=best.get("name"),
        spot_id=str(chosen_spot.get("_id")) if chosen_spot else None,
        spot_number=chosen_spot.get("spot_number") if chosen_spot else None,
        reason="Closest lot with available matching spots",
    )


class StartBookingRequest(BaseModel):
    lot_id: str
    spot_id: str
    vehicle_plate: str
    user_name: Optional[str] = None

class BookingResponse(BaseModel):
    booking_id: str
    status: str


@app.post("/book/start", response_model=BookingResponse)
def start_booking(req: StartBookingRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    if ObjectId is None:
        raise HTTPException(status_code=500, detail="ObjectId not available")

    # Verify lot exists
    try:
        _ = db["parkinglot"].find_one({"_id": ObjectId(req.lot_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid lot id")

    # Verify spot is free
    try:
        spot = db["parkingspot"].find_one({"_id": ObjectId(req.spot_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid spot id")

    if not spot:
        raise HTTPException(status_code=404, detail="Spot not found")
    if spot.get("is_occupied"):
        raise HTTPException(status_code=409, detail="Spot already occupied")

    # Mark occupied
    db["parkingspot"].update_one({"_id": spot["_id"]}, {"$set": {"is_occupied": True}})

    booking_id = create_document(
        "booking",
        Booking(
            lot_id=req.lot_id,
            spot_id=req.spot_id,
            vehicle_plate=req.vehicle_plate,
            user_name=req.user_name,
            start_time=datetime.now(timezone.utc),
            status="active",
        ),
    )

    return BookingResponse(booking_id=booking_id, status="active")


class EndBookingRequest(BaseModel):
    booking_id: str

class EndBookingResult(BaseModel):
    duration_minutes: float
    amount_due: float
    currency: str = "USD"


@app.post("/book/end", response_model=EndBookingResult)
def end_booking(req: EndBookingRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    if ObjectId is None:
        raise HTTPException(status_code=500, detail="ObjectId not available")

    try:
        b = db["booking"].find_one({"_id": ObjectId(req.booking_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid booking id")

    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")
    if b.get("status") != "active":
        raise HTTPException(status_code=409, detail="Booking already closed")

    # Price
    try:
        lot = db["parkinglot"].find_one({"_id": ObjectId(b.get("lot_id"))}) if b.get("lot_id") else None
    except Exception:
        lot = None
    price_per_hour = lot.get("price_per_hour", 5.0) if lot else 5.0

    start = b.get("start_time") or datetime.now(timezone.utc)
    end = datetime.now(timezone.utc)
    minutes = (end - start).total_seconds() / 60.0
    cost = round((minutes / 60.0) * float(price_per_hour), 2)

    # Close booking
    db["booking"].update_one({"_id": b["_id"]}, {"$set": {"status": "completed", "end_time": end}})

    # Free spot
    try:
        db["parkingspot"].update_one({"_id": ObjectId(b.get("spot_id"))}, {"$set": {"is_occupied": False}})
    except Exception:
        pass

    return EndBookingResult(duration_minutes=minutes, amount_due=cost)


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available" if db is None else "✅ Connected",
    }
    try:
        response["collections"] = db.list_collection_names() if db else []
    except Exception as e:
        response["database"] = f"⚠️ {str(e)[:50]}"
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
