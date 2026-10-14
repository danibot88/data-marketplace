from django.contrib import admin

from .models import Category, Dataset, DatasetAccess, Order, OrderItem


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    list_filter = ("is_active",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Dataset)
class DatasetAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "file_format", "price", "currency", "is_active", "is_featured")
    list_filter = ("is_active", "is_featured", "file_format", "currency", "category")
    search_fields = ("title", "description")
    prepopulated_fields = {"slug": ("title",)}


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("dataset", "unit_price")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "total_amount", "status", "gateway_provider", "created_at")
    list_filter = ("status", "gateway_provider")
    readonly_fields = ("idempotency_key", "created_at", "updated_at")
    inlines = (OrderItemInline,)


@admin.register(DatasetAccess)
class DatasetAccessAdmin(admin.ModelAdmin):
    list_display = ("user", "dataset", "download_count", "is_revoked", "created_at")
    list_filter = ("is_revoked",)
    search_fields = ("user__username", "dataset__title")
    readonly_fields = ("token", "download_count", "last_downloaded_at")
