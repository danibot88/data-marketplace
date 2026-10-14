from .models import Category


def navigation_categories(request):
    return {"navigation_categories": Category.objects.filter(is_active=True)[:8]}
