from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Any, Optional, Dict, Union
from datetime import datetime


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, description="User password (min 6 chars)")


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class GarminCredentials(BaseModel):
    username: str = Field(..., description="Garmin Connect Email Address")
    password: str = Field(..., description="Garmin Connect Password")


class UserResponse(BaseModel):
    id: str
    email: EmailStr
    created_at: datetime

    @field_validator('id', mode='before')
    @classmethod
    def coerce_id(cls, v):
        return str(v)

    class Config:
        from_attributes = True


class MetricResponse(BaseModel):
    time: datetime
    user_id: str
    metric: str
    value: Union[float, Dict[str, Any]]

    class Config:
        from_attributes = True


class InsightResponse(BaseModel):
    id: str
    user_id: str
    metric: str
    insight: str
    anomaly_detected: bool
    deviation_pct: Optional[float]
    created_at: datetime

    @field_validator('id', 'user_id', mode='before')
    @classmethod
    def coerce_uuid(cls, v):
        return str(v)

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    question: str = Field(..., description="The query for the health analytics bot")
    metric: str = Field(
        ...,
        description="The metric context to query (e.g. hrv, sleep, stress, activity, body_battery, vo2max, steps)"
    )
