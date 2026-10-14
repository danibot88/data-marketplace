from django.urls import path

from . import views

app_name = "marketplace"

urlpatterns = [
    path("", views.home, name="home"),
    path("datasets/", views.dataset_list, name="dataset_list"),
    path("datasets/<slug:slug>/", views.dataset_detail, name="dataset_detail"),
    path("datasets/<slug:slug>/preview/", views.dataset_preview, name="dataset_preview"),
    path("datasets/<slug:slug>/sample-data/", views.sample_data, name="sample_data"),
    path("datasets/<slug:slug>/comprar/", views.create_checkout, name="create_checkout"),
    path("pagamento/mock/<int:order_id>/", views.mock_checkout, name="mock_checkout"),
    path("webhooks/<str:provider>/", views.payment_webhook, name="webhook"),
    path("meus-dados/", views.dashboard, name="dashboard"),
    path("download/<uuid:token>/", views.secure_download, name="download"),
]
