import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse

from .storage import private_storage


def validate_sample_size(value):
    if value.size > 20 * 1024 * 1024:
        raise ValidationError("A amostra deve ter no máximo 20 MB.")


class Category(models.Model):
    name = models.CharField("nome", max_length=80, unique=True)
    slug = models.SlugField(unique=True)
    description = models.CharField("descrição", max_length=180, blank=True)
    is_active = models.BooleanField("ativa", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "categoria"
        verbose_name_plural = "categorias"

    def __str__(self):
        return self.name


class Dataset(models.Model):
    class Currency(models.TextChoices):
        BRL = "BRL", "Real brasileiro"
        USD = "USD", "Dólar americano"

    class FileFormat(models.TextChoices):
        CSV = "CSV", "CSV"
        PARQUET = "PARQUET", "Parquet"
        JSON = "JSON", "JSON"
        SQLITE = "SQLITE", "SQLite"

    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="datasets")
    title = models.CharField("título", max_length=180)
    slug = models.SlugField(unique=True)
    description = models.TextField("descrição")
    short_description = models.CharField("resumo", max_length=220, blank=True)
    price = models.DecimalField("preço", max_digits=12, decimal_places=2)
    currency = models.CharField("moeda", max_length=3, choices=Currency.choices, default=Currency.BRL)
    file_path = models.CharField("caminho do arquivo privado", max_length=500)
    sample_file = models.FileField(
        "arquivo de amostra",
        upload_to="samples/%Y/%m/",
        storage=private_storage,
        validators=[
            FileExtensionValidator(allowed_extensions=["csv", "json", "parquet", "sqlite", "sqlite3", "db"]),
            validate_sample_size,
        ],
    )
    file_format = models.CharField("formato", max_length=10, choices=FileFormat.choices)
    file_size_bytes = models.BigIntegerField("tamanho em bytes", default=0)
    row_count = models.BigIntegerField("quantidade de linhas", default=0)
    column_count = models.PositiveIntegerField("quantidade de colunas", default=0)
    schema_metadata = models.JSONField("metadados do esquema", default=list, blank=True)
    is_featured = models.BooleanField("destaque", default=False)
    is_active = models.BooleanField("ativo", default=True)
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["-is_featured", "-created_at"]
        indexes = [
            models.Index(fields=["is_active", "category"]),
            models.Index(fields=["file_format", "price"]),
        ]
        constraints = [models.CheckConstraint(condition=Q(price__gte=0), name="dataset_price_nonnegative")]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("marketplace:dataset_detail", kwargs={"slug": self.slug})

    def clean(self):
        super().clean()
        root = settings.PRIVATE_DATA_ROOT.resolve()
        candidate = self.full_file_path.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValidationError({"file_path": "O arquivo completo precisa estar dentro de PRIVATE_DATA_ROOT."}) from exc

    @property
    def full_file_path(self) -> Path:
        configured = Path(self.file_path)
        return configured if configured.is_absolute() else settings.PRIVATE_DATA_ROOT / configured


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendente"
        PAID = "PAID", "Pago"
        FAILED = "FAILED", "Falhou"
        REFUNDED = "REFUNDED", "Reembolsado"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    total_amount = models.DecimalField("valor total", max_digits=12, decimal_places=2)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    gateway_provider = models.CharField(max_length=30)
    gateway_order_id = models.CharField(max_length=120, blank=True, db_index=True)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.CheckConstraint(condition=Q(total_amount__gte=0), name="order_total_nonnegative")]

    def __str__(self):
        return f"Pedido {self.pk} — {self.get_status_display()}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    dataset = models.ForeignKey(Dataset, on_delete=models.PROTECT, related_name="order_items")
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order", "dataset"], name="unique_dataset_per_order"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="order_item_price_nonnegative"),
        ]

    def __str__(self):
        return f"{self.dataset} em {self.order}"


class DatasetAccess(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="dataset_accesses")
    dataset = models.ForeignKey(Dataset, on_delete=models.PROTECT, related_name="accesses")
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="granted_accesses")
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    download_count = models.PositiveIntegerField(default=0)
    last_downloaded_at = models.DateTimeField(null=True, blank=True)
    is_revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "acesso a dataset"
        verbose_name_plural = "acessos a datasets"
        constraints = [models.UniqueConstraint(fields=["user", "dataset"], name="unique_user_dataset_access")]
        indexes = [models.Index(fields=["user", "is_revoked"])]

    def clean(self):
        if self.order_id and self.user_id and self.order.user_id != self.user_id:
            raise ValidationError("O pedido precisa pertencer ao mesmo usuário do acesso.")

    def __str__(self):
        return f"{self.user} → {self.dataset}"
