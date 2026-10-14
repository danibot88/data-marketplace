import hashlib
import hmac
import json
import secrets
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.urls import reverse

from .models import Order


class PaymentError(Exception):
    pass


class InvalidWebhookSignature(PaymentError):
    pass


class BasePaymentGateway(ABC):
    provider = "base"

    @abstractmethod
    def create_checkout_session(self, order: Order) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def process_webhook(self, request: HttpRequest) -> tuple[bool, Order]:
        raise NotImplementedError


class MockPaymentGateway(BasePaymentGateway):
    provider = "mock"

    @staticmethod
    def signature(payload: bytes) -> str:
        return hmac.new(settings.MOCK_WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()

    def create_checkout_session(self, order: Order) -> dict[str, Any]:
        gateway_id = order.gateway_order_id or f"mock_{secrets.token_hex(12)}"
        if not order.gateway_order_id:
            order.gateway_order_id = gateway_id
            order.save(update_fields=["gateway_order_id", "updated_at"])
        return {
            "id": gateway_id,
            "checkout_url": reverse("marketplace:mock_checkout", kwargs={"order_id": order.pk}),
        }

    def process_webhook(self, request: HttpRequest) -> tuple[bool, Order]:
        signature = request.headers.get("X-Mock-Signature", "")
        if not signature or not hmac.compare_digest(signature, self.signature(request.body)):
            raise InvalidWebhookSignature("Assinatura mock inválida.")
        try:
            data = json.loads(request.body)
            order = Order.objects.get(idempotency_key=data["idempotency_key"], gateway_provider=self.provider)
        except (json.JSONDecodeError, KeyError, Order.DoesNotExist) as exc:
            raise PaymentError("Payload mock inválido.") from exc
        return data.get("status") == "paid", order


class MercadoPagoGateway(BasePaymentGateway):
    """Adaptador HTTP sem acoplamento ao SDK do provedor."""

    provider = "mercadopago"
    api_url = "https://api.mercadopago.com/checkout/preferences"

    def create_checkout_session(self, order: Order) -> dict[str, Any]:
        if not settings.MERCADOPAGO_ACCESS_TOKEN:
            raise PaymentError("MERCADOPAGO_ACCESS_TOKEN não configurado.")
        item = order.items.select_related("dataset").get()
        payload = json.dumps({
            "items": [{
                "id": str(item.dataset_id),
                "title": item.dataset.title,
                "quantity": 1,
                "currency_id": item.dataset.currency,
                "unit_price": float(item.unit_price),
            }],
            "external_reference": str(order.idempotency_key),
            "notification_url": f"{settings.SITE_URL}{reverse('marketplace:webhook', kwargs={'provider': self.provider})}",
            "back_urls": {
                "success": f"{settings.SITE_URL}{reverse('marketplace:dashboard')}",
                "failure": f"{settings.SITE_URL}{item.dataset.get_absolute_url()}",
                "pending": f"{settings.SITE_URL}{reverse('marketplace:dashboard')}",
            },
            "auto_return": "approved",
        }).encode()
        request = urllib.request.Request(
            self.api_url,
            data=payload,
            headers={
                "Authorization": f"Bearer {settings.MERCADOPAGO_ACCESS_TOKEN}",
                "Content-Type": "application/json",
                "X-Idempotency-Key": str(order.idempotency_key),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = json.load(response)
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise PaymentError("Não foi possível iniciar o checkout no Mercado Pago.") from exc
        order.gateway_order_id = str(data["id"])
        order.save(update_fields=["gateway_order_id", "updated_at"])
        return {"id": data["id"], "checkout_url": data["init_point"]}

    def _verify_signature(self, request: HttpRequest) -> None:
        # Formato documentado pelo Mercado Pago: id, request-id e timestamp no manifesto.
        signature = request.headers.get("X-Signature", "")
        request_id = request.headers.get("X-Request-Id", "")
        parts = {key.strip(): value.strip() for key, value in (part.split("=", 1) for part in signature.split(",") if "=" in part)}
        timestamp, received = parts.get("ts", ""), parts.get("v1", "")
        data_id = request.GET.get("data.id", "").lower()
        manifest = f"id:{data_id};request-id:{request_id};ts:{timestamp};"
        expected = hmac.new(settings.MERCADOPAGO_WEBHOOK_SECRET.encode(), manifest.encode(), hashlib.sha256).hexdigest()
        if not settings.MERCADOPAGO_WEBHOOK_SECRET or not received or not hmac.compare_digest(received, expected):
            raise InvalidWebhookSignature("Assinatura Mercado Pago inválida.")

    def process_webhook(self, request: HttpRequest) -> tuple[bool, Order]:
        self._verify_signature(request)
        payment_id = request.GET.get("data.id")
        if not payment_id or not settings.MERCADOPAGO_ACCESS_TOKEN:
            raise PaymentError("Notificação Mercado Pago incompleta.")
        api_request = urllib.request.Request(
            f"https://api.mercadopago.com/v1/payments/{payment_id}",
            headers={"Authorization": f"Bearer {settings.MERCADOPAGO_ACCESS_TOKEN}"},
        )
        try:
            with urllib.request.urlopen(api_request, timeout=15) as response:
                payment = json.load(response)
            order = Order.objects.get(idempotency_key=payment["external_reference"], gateway_provider=self.provider)
        except (urllib.error.URLError, json.JSONDecodeError, KeyError, Order.DoesNotExist) as exc:
            raise PaymentError("Pagamento Mercado Pago inválido ou desconhecido.") from exc
        return payment.get("status") == "approved", order


GATEWAYS = {"mock": MockPaymentGateway, "mercadopago": MercadoPagoGateway}


def get_gateway(provider: str | None = None) -> BasePaymentGateway:
    selected = (provider or settings.PAYMENT_GATEWAY).lower()
    try:
        return GATEWAYS[selected]()
    except KeyError as exc:
        raise PaymentError(f"Gateway não suportado: {selected}") from exc
