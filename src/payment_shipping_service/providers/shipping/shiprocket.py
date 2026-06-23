"""
Shiprocket shipping provider.

When MOCK_PROVIDERS=true: realistic mock rates / shipment data, no API calls.
When MOCK_PROVIDERS=false: real Shiprocket API v2 calls.

Shiprocket API: https://apiv2.shiprocket.in/v1/external
  - Auth: JWT from email/password login, expires ~24h.
  - Weights in kg, dimensions in cm.
"""
import os
import uuid
import requests
from datetime import datetime, timezone, timedelta
from .base import ShippingProvider, RateOption, ShipmentResult, TrackingResult, TrackingEventData
from typing import List

SHIPROCKET_BASE = "https://apiv2.shiprocket.in/v1/external"
MOCK = os.getenv("MOCK_PROVIDERS", "true").lower() == "true"

WAREHOUSE = {
    "name":    os.getenv("WAREHOUSE_NAME",    "ECommerce Fulfillment Center"),
    "address": os.getenv("WAREHOUSE_ADDRESS", "123 Warehouse Road"),
    "city":    os.getenv("WAREHOUSE_CITY",    "Mumbai"),
    "state":   os.getenv("WAREHOUSE_STATE",   "Maharashtra"),
    "pincode": os.getenv("WAREHOUSE_PINCODE", "400069"),
    "phone":   os.getenv("WAREHOUSE_PHONE",   "9876543210"),
    "email":   os.getenv("WAREHOUSE_EMAIL",   "fulfillment@ecommerce.com"),
}


class ShiprocketProvider(ShippingProvider):
    def __init__(self):
        self.email    = os.getenv("SHIPROCKET_EMAIL",    "")
        self.password = os.getenv("SHIPROCKET_PASSWORD", "")
        self._token         = None
        self._token_expiry  = None

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._token and self._token_expiry and now < self._token_expiry:
            return self._token

        resp = requests.post(
            f"{SHIPROCKET_BASE}/auth/login",
            json={"email": self.email, "password": self.password},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token        = data["token"]
        self._token_expiry = now + timedelta(hours=23)
        return self._token

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self._get_token()}"}

    # ── Rates ─────────────────────────────────────────────────────────────────

    def get_rates(
        self,
        origin_pincode:      str,
        destination_pincode: str,
        weight_kg:           float,
        cod:                 bool = False,
    ) -> List[RateOption]:
        if MOCK:
            return _mock_rates(origin_pincode, destination_pincode, weight_kg, cod)

        params = {
            "pickup_postcode":   origin_pincode,
            "delivery_postcode": destination_pincode,
            "weight":            weight_kg,
            "cod":               1 if cod else 0,
        }
        resp = requests.get(
            f"{SHIPROCKET_BASE}/courier/serviceability/",
            params=params,
            headers=self._h(),
            timeout=15,
        )
        resp.raise_for_status()
        couriers = resp.json().get("data", {}).get("available_courier_companies", [])

        return [
            RateOption(
                courier_name=c["courier_name"],
                service_type=_map_service(c),
                rate_amount=float(c["freight_charge"]),
                estimated_days=int(c.get("estimated_delivery_days", 5)),
                cod_available=bool(c.get("cod", 0)),
                courier_id=str(c.get("courier_company_id", "")),
            )
            for c in couriers
        ]

    # ── Create shipment ───────────────────────────────────────────────────────

    def create_shipment(
        self,
        checkout_order_id: str,
        order_details:     dict,
        rate:              RateOption | None = None,
    ) -> ShipmentResult:
        if MOCK:
            return _mock_shipment(checkout_order_id, order_details, rate)

        # Build Shiprocket order payload
        dest = order_details.get("destination", {})
        items = order_details.get("items", [])

        payload = {
            "order_id":           checkout_order_id,
            "order_date":         datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
            "pickup_location":    WAREHOUSE["name"],
            "billing_customer_name": dest.get("name", "Customer"),
            "billing_address":    dest.get("address", ""),
            "billing_city":       dest.get("city", ""),
            "billing_pincode":    dest.get("pincode", ""),
            "billing_state":      dest.get("state", ""),
            "billing_country":    "India",
            "billing_email":      dest.get("email", WAREHOUSE["email"]),
            "billing_phone":      dest.get("phone", ""),
            "shipping_is_billing": 1,
            "order_items":        [
                {
                    "name":       i.get("product_name", "Item"),
                    "sku":        i.get("product_id", "SKU"),
                    "units":      i.get("quantity", 1),
                    "selling_price": i.get("unit_price", 0),
                }
                for i in items
            ],
            "payment_method":    "Prepaid" if not order_details.get("cod") else "COD",
            "sub_total":         order_details.get("amount", 0),
            "weight":            order_details.get("weight_kg", 0.5),
        }
        if rate and rate.courier_id:
            payload["courier_id"] = int(rate.courier_id)

        resp = requests.post(
            f"{SHIPROCKET_BASE}/orders/create/adhoc",
            json=payload,
            headers=self._h(),
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        return ShipmentResult(
            provider_shipment_id=str(data.get("shipment_id", "")),
            awb_number=data.get("awb_code", ""),
            courier_name=data.get("courier_name", rate.courier_name if rate else ""),
            label_url=data.get("label_url", ""),
            pickup_scheduled_at=data.get("pickup_scheduled_date", ""),
            provider_raw=data,
        )

    # ── Track ─────────────────────────────────────────────────────────────────

    def track(self, awb_number: str) -> TrackingResult:
        if MOCK:
            return _mock_tracking(awb_number)

        resp = requests.get(
            f"{SHIPROCKET_BASE}/courier/track/awb/{awb_number}",
            headers=self._h(),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        tracking = data.get("tracking_data", {})
        shipment  = tracking.get("shipment_track", [{}])[0]
        activities = tracking.get("shipment_track_activities", [])

        events = [
            TrackingEventData(
                status=a.get("activity", ""),
                description=a.get("activity", ""),
                location=a.get("location", ""),
                timestamp=a.get("date", ""),
            )
            for a in activities
        ]

        return TrackingResult(
            awb_number=awb_number,
            current_status=shipment.get("current_status", "In Transit"),
            estimated_delivery=shipment.get("etd", ""),
            events=events,
            provider_raw=data,
        )

    # ── Cancel ────────────────────────────────────────────────────────────────

    def cancel(self, awb_number: str) -> dict:
        if MOCK:
            return {"message": "Shipment cancelled", "awb_number": awb_number, "status": "cancelled"}

        resp = requests.post(
            f"{SHIPROCKET_BASE}/orders/cancel",
            json={"awbs": [awb_number]},
            headers=self._h(),
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()


# ── Mock helpers ──────────────────────────────────────────────────────────────

def _map_service(courier: dict) -> str:
    name = (courier.get("courier_name") or "").lower()
    if "express" in name or "bluedart" in name:
        return "express"
    if "overnight" in name or "priority" in name:
        return "overnight"
    return "standard"


def _mock_rates(
    origin: str, destination: str, weight_kg: float, cod: bool
) -> List[RateOption]:
    try:
        zone_diff = abs(int(origin[:3]) - int(destination[:3])) // 100
    except ValueError:
        zone_diff = 3
    base = max(50.0, 40 + zone_diff * 15 + weight_kg * 25)
    options = [
        ("Delhivery",  "standard", 1.00, 5 + zone_diff, True,  "101"),
        ("Bluedart",   "express",  1.65, 2,              False, "102"),
        ("Ekart",      "standard", 0.88, 6 + zone_diff,  True,  "103"),
        ("Xpressbees", "express",  1.40, 3,              True,  "104"),
        ("DTDC",       "standard", 0.95, 5 + zone_diff,  True,  "105"),
    ]
    return [
        RateOption(
            courier_name=name,
            service_type=svc,
            rate_amount=round(base * mult, 2),
            estimated_days=days,
            cod_available=cod_ok,
            courier_id=cid,
        )
        for name, svc, mult, days, cod_ok, cid in options
        if (not cod) or cod_ok
    ]


def _mock_shipment(
    checkout_order_id: str, order_details: dict, rate: RateOption | None
) -> ShipmentResult:
    now = datetime.now(timezone.utc)
    days = rate.estimated_days if rate else 5
    pickup = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    awb = f"AWB{uuid.uuid4().hex[:12].upper()}"
    ship_id = f"SR{uuid.uuid4().hex[:8].upper()}"
    courier = rate.courier_name if rate else "Delhivery"
    return ShipmentResult(
        provider_shipment_id=ship_id,
        awb_number=awb,
        courier_name=courier,
        label_url=f"https://mock-labels.shiprocket.in/{ship_id}.pdf",
        pickup_scheduled_at=pickup,
        provider_raw={
            "shipment_id":  ship_id,
            "awb_code":     awb,
            "courier_name": courier,
            "status":       "Shipment Created",
        },
    )


def _mock_tracking(awb_number: str) -> TrackingResult:
    now = datetime.now(timezone.utc)
    events = [
        TrackingEventData("Shipment Created",      "Order picked up from seller",        "Mumbai",    (now - timedelta(days=3)).isoformat()),
        TrackingEventData("In Transit",            "Arrived at origin facility",         "Mumbai Hub",(now - timedelta(days=2)).isoformat()),
        TrackingEventData("In Transit",            "Departed from Mumbai Hub",           "Mumbai Hub",(now - timedelta(days=2, hours=6)).isoformat()),
        TrackingEventData("In Transit",            "Arrived at destination sort center", "Delhi Hub", (now - timedelta(days=1)).isoformat()),
        TrackingEventData("Out for Delivery",      "With delivery agent",                "Delhi",     (now - timedelta(hours=4)).isoformat()),
    ]
    return TrackingResult(
        awb_number=awb_number,
        current_status="Out for Delivery",
        estimated_delivery=(now + timedelta(hours=6)).strftime("%Y-%m-%d"),
        events=events,
        provider_raw={"awb": awb_number, "mock": True},
    )


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: ShiprocketProvider | None = None


def get_shiprocket() -> ShiprocketProvider:
    global _instance
    if _instance is None:
        _instance = ShiprocketProvider()
    return _instance
