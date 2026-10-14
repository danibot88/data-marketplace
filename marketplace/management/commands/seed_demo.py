import csv
import json
import sqlite3
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand
from django.utils.text import slugify

from marketplace.models import Category, Dataset


DEMO_DATASETS = [
    ("Economia", "Indicadores econômicos do Brasil", "Série histórica de inflação, juros e atividade econômica.", "CSV", "79.90"),
    ("Mobilidade", "Fluxo de mobilidade urbana", "Viagens agregadas por região, horário e modal.", "PARQUET", "129.90"),
    ("Varejo", "Painel de preços no varejo", "Cesta de produtos e variações mensais por capital.", "CSV", "59.90"),
    ("Demografia", "Perfil demográfico municipal", "Indicadores populacionais de municípios brasileiros.", "JSON", "89.90"),
    ("Meio ambiente", "Séries climáticas consolidadas", "Temperatura e precipitação agregadas por estação.", "CSV", "109.90"),
    ("Empresas", "Mapa setorial de empresas", "Empresas agregadas por atividade, porte e localização.", "CSV", "149.90"),
]


class Command(BaseCommand):
    help = "Cria um catálogo demonstrativo seguro para desenvolvimento."

    def handle(self, *args, **options):
        demo_dir = settings.PRIVATE_DATA_ROOT / "demo_source"
        demo_dir.mkdir(parents=True, exist_ok=True)
        for index, (category_name, title, summary, file_format, price) in enumerate(DEMO_DATASETS, start=1):
            category, _ = Category.objects.get_or_create(
                slug=slugify(category_name), defaults={"name": category_name, "description": f"Dados de {category_name.lower()}"}
            )
            slug = slugify(title)
            source = demo_dir / f"{slug}.csv"
            rows = [[year, ["Sul", "Sudeste", "Nordeste"][year % 3], index * 10 + year % 7] for year in range(2018, 2026)]
            with source.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["ano", "regiao", "indice"])
                writer.writerows(rows)
            extension = {"CSV": "csv", "PARQUET": "parquet", "JSON": "json", "SQLITE": "sqlite"}[file_format]
            dataset, created = Dataset.objects.get_or_create(
                slug=slug,
                defaults={
                    "category": category,
                    "title": title,
                    "description": f"## Sobre esta base\n\n{summary}\n\nA base demonstrativa inclui documentação de campos e uma amostra navegável.",
                    "short_description": summary,
                    "price": price,
                    "file_path": f"datasets/{slug}.{extension}",
                    "file_format": file_format,
                    "file_size_bytes": source.stat().st_size,
                    "row_count": 8,
                    "column_count": 3,
                    "schema_metadata": [
                        {"name": "ano", "type": "integer", "description": "Ano de referência"},
                        {"name": "regiao", "type": "string", "description": "Recorte territorial"},
                        {"name": "indice", "type": "number", "description": "Valor do indicador"},
                    ],
                    "is_featured": index <= 4,
                },
            )
            if created:
                with source.open("rb") as sample:
                    dataset.sample_file.save(f"{slug}-sample.csv", File(sample), save=False)
                target = dataset.full_file_path
                target.parent.mkdir(parents=True, exist_ok=True)
                if file_format == "CSV":
                    target.write_bytes(source.read_bytes())
                elif file_format == "JSON":
                    target.write_text(json.dumps([dict(zip(["ano", "regiao", "indice"], row)) for row in rows], ensure_ascii=False), encoding="utf-8")
                elif file_format == "SQLITE":
                    with sqlite3.connect(target) as connection:
                        connection.execute("CREATE TABLE IF NOT EXISTS indicadores (ano INTEGER, regiao TEXT, indice REAL)")
                        connection.executemany("INSERT INTO indicadores VALUES (?, ?, ?)", rows)
                else:
                    import polars as pl
                    pl.DataFrame(rows, schema=["ano", "regiao", "indice"], orient="row").write_parquet(target)
                dataset.file_size_bytes = target.stat().st_size
                dataset.save()
        self.stdout.write(self.style.SUCCESS("Catálogo demonstrativo criado."))
