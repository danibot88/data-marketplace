import csv
import json
import sqlite3
from pathlib import Path

from django.db import transaction

from .models import Dataset, DatasetAccess, Order


@transaction.atomic
def mark_order_paid(order: Order) -> tuple[Order, bool]:
    locked = Order.objects.select_for_update().prefetch_related("items__dataset").get(pk=order.pk)
    if locked.status in {Order.Status.PAID, Order.Status.REFUNDED}:
        return locked, False
    locked.status = Order.Status.PAID
    locked.save(update_fields=["status", "updated_at"])
    for item in locked.items.all():
        DatasetAccess.objects.update_or_create(
            user=locked.user,
            dataset=item.dataset,
            defaults={"order": locked, "is_revoked": False},
        )
    return locked, True


def _normalize(value):
    if value is None:
        return ""
    if isinstance(value, (int, float, bool)):
        return value
    text = str(value)
    try:
        return int(text)
    except ValueError:
        try:
            return float(text.replace(",", "."))
        except ValueError:
            return text


def read_sample(dataset: Dataset, limit: int = 1000) -> tuple[list[str], list[dict]]:
    """Lê somente sample_file; nunca consulta dataset.full_file_path."""
    path = Path(dataset.sample_file.path)
    suffix = path.suffix.lower()
    fmt = dataset.file_format
    if suffix == ".csv" or (not suffix and fmt == Dataset.FileFormat.CSV):
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = [{key: _normalize(value) for key, value in row.items()} for _, row in zip(range(limit), reader)]
            return list(reader.fieldnames or []), rows
    if suffix == ".json" or (not suffix and fmt == Dataset.FileFormat.JSON):
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            data = data.get("data", [data])
        rows = [{key: _normalize(value) for key, value in row.items()} for row in data[:limit]]
        return list(rows[0].keys()) if rows else [], rows
    if suffix in {".sqlite", ".sqlite3", ".db"} or (not suffix and fmt == Dataset.FileFormat.SQLITE):
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            table = connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name LIMIT 1").fetchone()
            if not table:
                return [], []
            safe_table = table[0].replace('"', '""')
            cursor = connection.execute(f'SELECT * FROM "{safe_table}" LIMIT ?', (limit,))
            columns = [item[0] for item in cursor.description]
            return columns, [dict(zip(columns, map(_normalize, row))) for row in cursor.fetchall()]
    if suffix == ".parquet" or (not suffix and fmt == Dataset.FileFormat.PARQUET):
        try:
            import polars as pl
        except ImportError as exc:
            raise RuntimeError("Instale polars para visualizar amostras Parquet.") from exc
        frame = pl.scan_parquet(path).head(limit).collect()
        return frame.columns, [{key: _normalize(value) for key, value in row.items()} for row in frame.to_dicts()]
    return [], []
