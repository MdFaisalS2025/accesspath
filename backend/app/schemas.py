from pydantic import BaseModel, ConfigDict, Field


class RouteCompareRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "origin_lat": 47.6205,
                "origin_lon": -122.3493,
                "destination_lat": 47.6156,
                "destination_lon": -122.3366,
            }
        }
    )

    origin_lat: float = Field(..., ge=-90, le=90, description="Origin latitude, WGS84 degrees")
    origin_lon: float = Field(..., ge=-180, le=180, description="Origin longitude, WGS84 degrees")
    destination_lat: float = Field(..., ge=-90, le=90, description="Destination latitude, WGS84 degrees")
    destination_lon: float = Field(..., ge=-180, le=180, description="Destination longitude, WGS84 degrees")
