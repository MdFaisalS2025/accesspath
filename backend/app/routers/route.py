from fastapi import APIRouter, Depends, HTTPException, Request

from app.core import geo
from app.core.route_service import compare_routes
from app.dependencies import get_conn
from app.schemas import RouteCompareRequest

router = APIRouter()


@router.post("/route/compare")
def route_compare(body: RouteCompareRequest, request: Request, conn=Depends(get_conn)):
    """Compares shortest/accessible/confidence_aware routes between two
    coordinates. See docs/week5_api_report.md for example requests/responses
    and the full status-code/error-format reference."""
    graph = request.app.state.graph
    try:
        return compare_routes(
            conn, graph,
            body.origin_lat, body.origin_lon,
            body.destination_lat, body.destination_lon,
        )
    except geo.OutOfServiceAreaError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "out_of_service_area",
                "message": str(e),
                "supported_bounds": {
                    "min_lat": geo.SEATTLE_MIN_LAT, "max_lat": geo.SEATTLE_MAX_LAT,
                    "min_lon": geo.SEATTLE_MIN_LON, "max_lon": geo.SEATTLE_MAX_LON,
                },
            },
        )
    except geo.NoRoutableNetworkError as e:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "no_routable_network",
                "message": str(e),
                "max_snap_distance_m": e.max_distance_m,
            },
        )
