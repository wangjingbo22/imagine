from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, UUID4, model_validator

from app.schemas.trip import CityContext, ContractModel, GeoPoint


NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class SourceStatus(StrEnum):
    ONLINE = "ONLINE"
    VERIFIED_CACHE = "VERIFIED_CACHE"
    USER_CONFIRMED = "USER_CONFIRMED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class TravelMode(StrEnum):
    WALKING = "WALKING"
    TRANSIT = "TRANSIT"
    DRIVING = "DRIVING"
    BICYCLING = "BICYCLING"
    TAXI = "TAXI"


class FacilityType(StrEnum):
    ELEVATOR = "ELEVATOR"
    RAMP = "RAMP"
    NURSING_ROOM = "NURSING_ROOM"
    ACCESSIBLE_ENTRANCE = "ACCESSIBLE_ENTRANCE"


class FacilityEvidenceStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"


class Provenance(BaseModel):
    provider: Literal["AMAP", "APP_ESTIMATE"] = "AMAP"
    sourceStatus: SourceStatus
    fetchedAt: datetime
    isStale: bool = False


class PriceFact(BaseModel):
    amountCents: int | None = Field(default=None, ge=0)
    currency: Literal["CNY"] = "CNY"
    kind: NonBlankText
    provenance: Provenance

    @model_validator(mode="after")
    def validate_unknown_price(self) -> "PriceFact":
        amount_is_unknown = self.amountCents is None
        status_is_unknown = self.provenance.sourceStatus is SourceStatus.UNKNOWN
        if amount_is_unknown != status_is_unknown:
            raise ValueError(
                "UNKNOWN price must use amountCents=None and known price must not use UNKNOWN"
            )
        return self


class Place(BaseModel):
    placeId: NonBlankText
    name: NonBlankText
    address: str | None = None
    cityCode: NonBlankText
    adCode: str | None = None
    location: GeoPoint
    category: str | None = None
    telephone: str | None = None
    rating: float | None = None
    priceReference: PriceFact
    provenance: Provenance


class PlaceCollection(BaseModel):
    cityCode: NonBlankText
    total: int = Field(ge=0)
    places: list[Place]
    provenance: Provenance


class CityResolution(BaseModel):
    cityContext: CityContext
    adCode: str | None = None
    formattedAddress: str | None = None
    provenance: Provenance


class AddressResolution(BaseModel):
    formattedAddress: NonBlankText
    cityCode: NonBlankText
    adCode: str | None = None
    location: GeoPoint
    provenance: Provenance


class RouteStep(BaseModel):
    instruction: str | None = None
    road: str | None = None
    distanceMeters: int | None = Field(default=None, ge=0)
    durationSeconds: int | None = Field(default=None, ge=0)
    transport: str | None = None
    polyline: list[GeoPoint] = Field(default_factory=list)


class FacilityEvidence(BaseModel):
    facilityType: FacilityType
    label: NonBlankText
    status: FacilityEvidenceStatus
    message: NonBlankText
    referenceId: NonBlankText
    provenance: Provenance


class Route(BaseModel):
    routeId: NonBlankText
    mode: TravelMode
    origin: GeoPoint
    destination: GeoPoint
    distanceMeters: int = Field(ge=0)
    durationSeconds: int = Field(ge=0)
    walkingDistanceMeters: int | None = Field(default=None, ge=0)
    transferCount: int | None = Field(default=None, ge=0)
    steps: list[RouteStep] = Field(default_factory=list)
    facilityEvidence: list[FacilityEvidence] = Field(default_factory=list)
    priceReference: PriceFact
    provenance: Provenance


class RouteCollection(BaseModel):
    cityCode: NonBlankText
    routes: list[Route]
    provenance: Provenance


DataT = TypeVar("DataT")


class ApiResponse(BaseModel, Generic[DataT]):
    code: Literal[200] = 200
    message: Literal["success"] = "success"
    data: DataT


class ErrorResponse(BaseModel):
    code: str
    schemaVersion: Literal["1.0"] = "1.0"
    message: str
    retryable: bool = False
    errors: list[dict[str, Any]] = Field(default_factory=list)


class TripScopedRequest(ContractModel):
    # FastAPI has already decoded JSON before model validation; allow canonical
    # UUID4/enum JSON strings to be converted at this transport boundary.
    model_config = ConfigDict(strict=False)

    schema_version: Literal["1.0"] = "1.0"
    trip_id: UUID4
    city_context: CityContext


class CityResolveRequest(ContractModel):
    model_config = ConfigDict(strict=False)

    schema_version: Literal["1.0"] = "1.0"
    city_name: NonBlankText


class SuggestionRequest(TripScopedRequest):
    keywords: NonBlankText
    types: list[str] = Field(default_factory=list, max_length=10)
    limit: int = Field(default=10, ge=1, le=25)


class PlaceSearchRequest(TripScopedRequest):
    keywords: NonBlankText
    types: list[str] = Field(default_factory=list, max_length=10)
    page: int = Field(default=1, ge=1, le=100)
    page_size: int = Field(default=20, ge=1, le=25)


class NearbySearchRequest(TripScopedRequest):
    center: GeoPoint
    radius_meters: int = Field(default=3_000, ge=0, le=50_000)
    keywords: str | None = None
    types: list[str] = Field(default_factory=list, max_length=10)
    page: int = Field(default=1, ge=1, le=100)
    page_size: int = Field(default=20, ge=1, le=25)

    @model_validator(mode="after")
    def require_filter(self) -> "NearbySearchRequest":
        if not (self.keywords and self.keywords.strip()) and not self.types:
            raise ValueError("keywords or types is required")
        return self


class PlaceDetailRequest(TripScopedRequest):
    place_id: NonBlankText


class ForwardGeocodingRequest(TripScopedRequest):
    address: NonBlankText


class ReverseGeocodingRequest(TripScopedRequest):
    location: GeoPoint


class RoutePlanRequest(TripScopedRequest):
    origin: GeoPoint
    destination: GeoPoint
    mode: TravelMode
    strategy: int | None = Field(default=None, ge=0, le=20)
