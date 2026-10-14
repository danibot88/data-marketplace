import json
import mimetypes
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import F, Q
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django_ratelimit.decorators import ratelimit

from .forms import SignupForm
from .models import Category, Dataset, DatasetAccess, Order, OrderItem
from .payments import InvalidWebhookSignature, MockPaymentGateway, PaymentError, get_gateway
from .services import mark_order_paid, read_sample


def home(request):
    datasets = Dataset.objects.filter(is_active=True).select_related("category")
    return render(request, "marketplace/home.html", {
        "featured": datasets.filter(is_featured=True)[:6],
        "latest": datasets[:10],
        "categories": Category.objects.filter(is_active=True),
    })


def dataset_list(request):
    datasets = Dataset.objects.filter(is_active=True).select_related("category")
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    file_format = request.GET.get("format", "").strip().upper()
    min_price, max_price = request.GET.get("min_price"), request.GET.get("max_price")
    if query:
        datasets = datasets.filter(Q(title__icontains=query) | Q(description__icontains=query))
    if category:
        datasets = datasets.filter(category__slug=category)
    if file_format in Dataset.FileFormat.values:
        datasets = datasets.filter(file_format=file_format)
    try:
        if min_price:
            datasets = datasets.filter(price__gte=Decimal(min_price))
        if max_price:
            datasets = datasets.filter(price__lte=Decimal(max_price))
    except (InvalidOperation, ValueError, TypeError):
        messages.warning(request, "A faixa de preço informada é inválida.")
    return render(request, "marketplace/dataset_list.html", {
        "datasets": datasets,
        "categories": Category.objects.filter(is_active=True),
        "formats": Dataset.FileFormat.choices,
    })


def dataset_detail(request, slug):
    dataset = get_object_or_404(Dataset.objects.select_related("category"), slug=slug, is_active=True)
    has_access = request.user.is_authenticated and DatasetAccess.objects.filter(
        user=request.user, dataset=dataset, is_revoked=False
    ).exists()
    return render(request, "marketplace/dataset_detail.html", {"dataset": dataset, "has_access": has_access})


@ratelimit(key="ip", rate="60/m", method="GET", block=True)
def dataset_preview(request, slug):
    dataset = get_object_or_404(Dataset, slug=slug, is_active=True)
    columns, rows = read_sample(dataset)
    query = request.GET.get("q", "").strip().casefold()
    if query:
        rows = [row for row in rows if any(query in str(value).casefold() for value in row.values())]
    try:
        page = max(int(request.GET.get("page", 1)), 1)
    except ValueError:
        page = 1
    per_page = 20
    start = (page - 1) * per_page
    return render(request, "marketplace/partials/preview_table.html", {
        "dataset": dataset,
        "columns": columns,
        "rows": rows[start:start + per_page],
        "page": page,
        "has_next": start + per_page < len(rows),
        "query": request.GET.get("q", ""),
    })


@require_GET
@ratelimit(key="ip", rate="30/m", method="GET", block=True)
def sample_data(request, slug):
    dataset = get_object_or_404(Dataset, slug=slug, is_active=True)
    columns, rows = read_sample(dataset, limit=100)
    if not rows:
        return JsonResponse({"labels": [], "values": [], "label": "Sem dados"})
    numeric = next((column for column in columns if any(isinstance(row.get(column), (int, float)) for row in rows)), None)
    if numeric:
        pairs = [(str(index + 1), row.get(numeric, 0)) for index, row in enumerate(rows[:20])]
        return JsonResponse({"labels": [p[0] for p in pairs], "values": [p[1] for p in pairs], "label": numeric})
    column = columns[0]
    counts = {}
    for row in rows:
        value = str(row.get(column, ""))
        counts[value] = counts.get(value, 0) + 1
    top = sorted(counts.items(), key=lambda item: item[1], reverse=True)[:10]
    return JsonResponse({"labels": [p[0] for p in top], "values": [p[1] for p in top], "label": column})


def signup(request):
    if request.user.is_authenticated:
        return redirect("marketplace:dashboard")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect("marketplace:dashboard")
    return render(request, "registration/signup.html", {"form": form})


@login_required
@require_POST
def create_checkout(request, slug):
    dataset = get_object_or_404(Dataset, slug=slug, is_active=True)
    if DatasetAccess.objects.filter(user=request.user, dataset=dataset, is_revoked=False).exists():
        messages.info(request, "Este dataset já está disponível em Meus Dados.")
        return redirect("marketplace:dashboard")
    gateway = get_gateway()
    with transaction.atomic():
        order = Order.objects.create(
            user=request.user,
            total_amount=dataset.price,
            gateway_provider=gateway.provider,
        )
        OrderItem.objects.create(order=order, dataset=dataset, unit_price=dataset.price)
    try:
        checkout = gateway.create_checkout_session(order)
    except PaymentError as exc:
        order.status = Order.Status.FAILED
        order.save(update_fields=["status", "updated_at"])
        messages.error(request, str(exc))
        return redirect(dataset)
    return redirect(checkout["checkout_url"])


@login_required
def mock_checkout(request, order_id):
    order = get_object_or_404(Order.objects.prefetch_related("items__dataset"), pk=order_id, user=request.user, gateway_provider="mock")
    if request.method == "POST" and order.status == Order.Status.PENDING:
        mark_order_paid(order)
        messages.success(request, "Pagamento simulado aprovado. Seu dataset já está disponível.")
        return redirect("marketplace:dashboard")
    return render(request, "marketplace/mock_checkout.html", {"order": order})


@csrf_exempt
@require_POST
@ratelimit(key="ip", rate="120/h", method="POST", block=True)
def payment_webhook(request, provider):
    try:
        paid, order = get_gateway(provider).process_webhook(request)
        if paid:
            mark_order_paid(order)
        elif order.status == Order.Status.PENDING:
            order.status = Order.Status.FAILED
            order.save(update_fields=["status", "updated_at"])
    except (InvalidWebhookSignature, PaymentError):
        return HttpResponse(status=400)
    return HttpResponse(status=200)


@login_required
def dashboard(request):
    accesses = DatasetAccess.objects.filter(user=request.user, is_revoked=False).select_related("dataset", "order")
    orders = Order.objects.filter(user=request.user).prefetch_related("items__dataset")
    return render(request, "marketplace/dashboard.html", {"accesses": accesses, "orders": orders})


def _safe_private_path(dataset: Dataset) -> Path:
    root = settings.PRIVATE_DATA_ROOT.resolve()
    candidate = dataset.full_file_path.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise Http404("Arquivo fora da área privada.") from exc
    if not candidate.is_file():
        raise Http404("Arquivo indisponível.")
    return candidate


def _file_chunks(path: Path, chunk_size: int = 1024 * 1024):
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            yield chunk


@ratelimit(key="user", rate="20/h", method="GET", block=True)
def secure_download(request, token):
    if not request.user.is_authenticated:
        raise Http404("Acesso não encontrado.")
    access = get_object_or_404(
        DatasetAccess.objects.select_related("dataset"), token=token, user=request.user, is_revoked=False
    )
    path = _safe_private_path(access.dataset)
    DatasetAccess.objects.filter(pk=access.pk).update(
        download_count=F("download_count") + 1,
        last_downloaded_at=timezone.now(),
    )
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if not settings.DEBUG:
        response = HttpResponse(content_type=content_type)
        relative = path.relative_to(settings.PRIVATE_DATA_ROOT).as_posix()
        response["X-Accel-Redirect"] = f"/_protected_data/{quote(relative)}"
        response["Content-Length"] = path.stat().st_size
    else:
        response = StreamingHttpResponse(_file_chunks(path), content_type=content_type)
    response["Content-Disposition"] = content_disposition_header(True, path.name)
    response["X-Content-Type-Options"] = "nosniff"
    return response
