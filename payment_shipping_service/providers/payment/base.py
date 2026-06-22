"""Abstract contract that every payment provider must implement."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class PaymentOrderResult:
    provider_order_id: str
    amount_paise: int           # always in paise (INR × 100)
    currency: str
    receipt: str
    status: str
    provider_raw: dict = field(default_factory=dict)


@dataclass
class PaymentVerifyResult:
    is_valid: bool
    provider_payment_id: str
    method: str                 # card | upi | netbanking | wallet | emi | cod
    amount_paise: int
    captured: bool
    card_last4: str = ""
    card_network: str = ""
    upi_vpa: str = ""
    provider_raw: dict = field(default_factory=dict)


@dataclass
class RefundResult:
    provider_refund_id: str
    amount_paise: int
    status: str                 # initiated | pending | processed | failed
    provider_raw: dict = field(default_factory=dict)


class PaymentProvider(ABC):
    @abstractmethod
    def create_order(self, amount_inr: float, receipt: str, notes: dict) -> PaymentOrderResult:
        ...

    @abstractmethod
    def verify_payment(
        self, order_id: str, payment_id: str, signature: str
    ) -> PaymentVerifyResult:
        ...

    @abstractmethod
    def fetch_payment(self, payment_id: str) -> dict:
        ...

    @abstractmethod
    def refund(
        self, payment_id: str, amount_inr: float, reason: str
    ) -> RefundResult:
        ...
