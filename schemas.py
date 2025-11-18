"""
Database Schemas for AI-powered Parking App

Each Pydantic model corresponds to a MongoDB collection (collection name is the
lowercased class name).
"""
from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime

# Users are kept for future extension/auth (not used heavily in demo UI)
class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    is_active: bool = Field(True, description="Whether user is active")

class ParkingLot(BaseModel):
    name: str = Field(..., description="Display name of the parking lot")
    latitude: float = Field(..., ge=-90, le=90, description="Latitude of lot")
    longitude: float = Field(..., ge=-180, le=180, description="Longitude of lot")
    address: Optional[str] = Field(None, description="Street address")
    price_per_hour: float = Field(..., ge=0, description="Base price per hour in USD")
    total_spots: int = Field(..., ge=1, description="Total number of spots in the lot")

class ParkingSpot(BaseModel):
    lot_id: str = Field(..., description="ID of the parking lot this spot belongs to")
    spot_number: str = Field(..., description="Human-readable spot label/number")
    vehicle_type: Literal["car", "motorcycle", "ev", "accessible"] = Field(
        "car", description="Spot category"
    )
    is_occupied: bool = Field(False, description="Whether the spot is currently occupied")

class Booking(BaseModel):
    lot_id: str = Field(..., description="ID of the parking lot")
    spot_id: str = Field(..., description="ID of the booked spot")
    vehicle_plate: str = Field(..., description="Vehicle plate number")
    user_name: Optional[str] = Field(None, description="Name for the booking")
    start_time: Optional[datetime] = Field(None, description="Start time; set by server if missing")
    end_time: Optional[datetime] = Field(None, description="End time; set when booking ends")
    status: Literal["active", "completed", "cancelled"] = Field(
        "active", description="Booking lifecycle state"
    )
