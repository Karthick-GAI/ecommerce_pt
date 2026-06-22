"""Abstract contract for shipping providers."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List


@dataclass
class RateOption:
    courier_name:   str
    service_type:   str       # standard | express | overnight
    rate_amount:    float     # INR
    estimated_days: int
    cod_available:  bool
    courier_id:     str = "" # provider-specific courier ID for booking


@dataclass
class ShipmentResult:
    provider_shipment_id: str
    awb_number:           str
    courier_name:         str
    label_url:            str
    pickup_scheduled_at:  str
    provider_raw:         dict = field(default_factory=dict)


@dataclass
class TrackingEventData:
    status:      str
    description: str
    location:    str
    timestamp:   str


@dataclass
class TrackingResult:
    awb_number:         str
    current_status:     str
    estimated_delivery: str
    events:             List[TrackingEventData] = field(default_factory=list)
    provider_raw:       dict = field(default_factory=dict)


class ShippingProvider(ABC):
    @abstractmethod
    def get_rates(
        self,
        origin_pincode:      str,
        destination_pincode: str,
        weight_kg:           float,
        cod:                 bool,
    ) -> List[RateOption]:
        ...

    @abstractmethod
    def create_shipment(
        self,
        checkout_order_id:    str,
        order_details:        dict,
        rate:                 RateOption | None,
    ) -> ShipmentResult:
        ...

    @abstractmethod
    def track(self, awb_number: str) -> TrackingResult:
        ...

    @abstractmethod
    def cancel(self, awb_number: str) -> dict:
        ...
