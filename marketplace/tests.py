import json
import hashlib
import hmac
import io
from pathlib import Path
from unittest.mock import PropertyMock, patch

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from .models import Category, Dataset, DatasetAccess, Order, OrderItem
from .payments import MercadoPagoGateway, MockPaymentGateway


class MarketplaceTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("comprador", "buyer@example.com", "senha-segura-123")
        cls.other_user = get_user_model().objects.create_user("visitante", "visitor@example.com", "senha-segura-123")
        category = Category.objects.create(name="Economia", slug="economia")
        cls.dataset = Dataset.objects.create(
            category=category,
            title="Indicadores econômicos",
            slug="indicadores-economicos",
            description="Amostra de indicadores.",
            short_description="Indicadores prontos para análise.",
            price="49.90",
            file_path="datasets/indicadores.csv",
            file_format=Dataset.FileFormat.CSV,
            file_size_bytes=32,
            row_count=2,
            column_count=2,
            schema_metadata=[{"name": "ano", "type": "integer", "description": "Ano"}],
        )
        cls.dataset.sample_file.save("indicadores_sample.csv", ContentFile(b"ano,valor\n2024,10\n2025,11\n"), save=True)
        full_path = cls.dataset.full_file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(b"arquivo completo privado")

    @classmethod
    def tearDownClass(cls):
        sample_path = Path(cls.dataset.sample_file.path)
        full_path = cls.dataset.full_file_path
        super().tearDownClass()
        for path in (sample_path, full_path):
            if path.exists():
                path.unlink()

    def create_access(self):
        order = Order.objects.create(
            user=self.user,
            total_amount=self.dataset.price,
            gateway_provider="mock",
            gateway_order_id="mock_test",
            status=Order.Status.PAID,
        )
        OrderItem.objects.create(order=order, dataset=self.dataset, unit_price=self.dataset.price)
        return DatasetAccess.objects.create(user=self.user, dataset=self.dataset, order=order)


class DownloadSecurityTests(MarketplaceTestCase):
    def test_anonymous_and_non_owner_receive_404(self):
        access = self.create_access()
        url = reverse("marketplace:download", args=[access.token])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.other_user)
        self.assertEqual(self.client.get(url).status_code, 404)

    @override_settings(DEBUG=False)
    def test_production_uses_x_accel_redirect(self):
        access = self.create_access()
        self.client.force_login(self.user)
        response = self.client.get(reverse("marketplace:download", args=[access.token]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["X-Accel-Redirect"], "/_protected_data/datasets/indicadores.csv")
        self.assertNotIn(b"arquivo completo", response.content)

    @override_settings(DEBUG=True)
    def test_development_streams_file_in_chunks(self):
        access = self.create_access()
        self.client.force_login(self.user)
        response = self.client.get(reverse("marketplace:download", args=[access.token]))
        self.assertTrue(response.streaming)
        self.assertEqual(b"".join(response.streaming_content), b"arquivo completo privado")
        access.refresh_from_db()
        self.assertEqual(access.download_count, 1)

    def test_path_outside_private_root_is_rejected(self):
        access = self.create_access()
        Dataset.objects.filter(pk=self.dataset.pk).update(file_path=str(Path.cwd() / "outside.csv"))
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("marketplace:download", args=[access.token])).status_code, 404)


class WebhookTests(MarketplaceTestCase):
    def setUp(self):
        self.order = Order.objects.create(
            user=self.user,
            total_amount=self.dataset.price,
            gateway_provider="mock",
            gateway_order_id="mock_webhook",
        )
        OrderItem.objects.create(order=self.order, dataset=self.dataset, unit_price=self.dataset.price)
        self.payload = json.dumps({
            "idempotency_key": str(self.order.idempotency_key),
            "status": "paid",
            "event_id": "evt_1",
        }).encode()
        self.url = reverse("marketplace:webhook", args=["mock"])

    def test_valid_webhook_grants_access(self):
        response = self.client.post(
            self.url,
            data=self.payload,
            content_type="application/json",
            HTTP_X_MOCK_SIGNATURE=MockPaymentGateway.signature(self.payload),
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.PAID)
        self.assertTrue(DatasetAccess.objects.filter(user=self.user, dataset=self.dataset).exists())

    def test_invalid_signature_is_rejected(self):
        response = self.client.post(
            self.url, data=self.payload, content_type="application/json", HTTP_X_MOCK_SIGNATURE="invalid"
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(DatasetAccess.objects.exists())

    def test_duplicate_webhook_is_idempotent(self):
        headers = {"HTTP_X_MOCK_SIGNATURE": MockPaymentGateway.signature(self.payload)}
        for _ in range(2):
            self.assertEqual(self.client.post(self.url, self.payload, content_type="application/json", **headers).status_code, 200)
        self.assertEqual(DatasetAccess.objects.filter(user=self.user, dataset=self.dataset).count(), 1)


class MercadoPagoAdapterTests(MarketplaceTestCase):
    @override_settings(MERCADOPAGO_WEBHOOK_SECRET="segredo-mp", MERCADOPAGO_ACCESS_TOKEN="token-mp")
    def test_signed_notification_is_verified_then_payment_is_queried(self):
        order = Order.objects.create(
            user=self.user,
            total_amount=self.dataset.price,
            gateway_provider="mercadopago",
            gateway_order_id="pref_123",
        )
        OrderItem.objects.create(order=order, dataset=self.dataset, unit_price=self.dataset.price)
        payment_id, request_id, timestamp = "987654", "request-abc", "1742505638683"
        manifest = f"id:{payment_id};request-id:{request_id};ts:{timestamp};"
        signature = hmac.new(b"segredo-mp", manifest.encode(), hashlib.sha256).hexdigest()
        request = RequestFactory().post(
            f"/webhooks/mercadopago/?data.id={payment_id}",
            data=b"{}",
            content_type="application/json",
            HTTP_X_SIGNATURE=f"ts={timestamp},v1={signature}",
            HTTP_X_REQUEST_ID=request_id,
        )
        api_response = io.BytesIO(json.dumps({
            "id": payment_id,
            "status": "approved",
            "external_reference": str(order.idempotency_key),
        }).encode())
        with patch("marketplace.payments.urllib.request.urlopen", return_value=api_response):
            paid, resolved_order = MercadoPagoGateway().process_webhook(request)
        self.assertTrue(paid)
        self.assertEqual(resolved_order, order)


class PreviewIsolationTests(MarketplaceTestCase):
    def test_preview_reads_sample_without_resolving_primary_file(self):
        with patch.object(Dataset, "full_file_path", new_callable=PropertyMock, side_effect=AssertionError("arquivo primário acessado")):
            response = self.client.get(reverse("marketplace:dataset_preview", args=[self.dataset.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2024")

    def test_sample_api_is_limited_and_available(self):
        response = self.client.get(reverse("marketplace:sample_data", args=[self.dataset.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("labels", response.json())


class PurchaseFlowTests(MarketplaceTestCase):
    def test_mock_purchase_is_completed_once(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("marketplace:create_checkout", args=[self.dataset.slug]))
        self.assertEqual(response.status_code, 302)
        order = Order.objects.get(user=self.user)
        self.assertEqual(order.status, Order.Status.PENDING)
        response = self.client.post(reverse("marketplace:mock_checkout", args=[order.pk]))
        self.assertRedirects(response, reverse("marketplace:dashboard"))
        self.assertEqual(DatasetAccess.objects.filter(user=self.user, dataset=self.dataset).count(), 1)

    def test_catalog_filters_by_category_and_format(self):
        response = self.client.get(reverse("marketplace:dataset_list"), {"category": "economia", "format": "CSV"})
        self.assertContains(response, self.dataset.title)

    def test_invalid_price_filter_does_not_break_catalog(self):
        response = self.client.get(reverse("marketplace:dataset_list"), {"min_price": "não-é-preço"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.dataset.title)
