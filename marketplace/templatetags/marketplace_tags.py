import bleach
import markdown
from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def markdown_safe(value):
    rendered = markdown.markdown(value or "", extensions=["extra", "sane_lists"])
    cleaned = bleach.clean(
        rendered,
        tags={"p", "br", "strong", "em", "ul", "ol", "li", "h2", "h3", "h4", "code", "pre", "a", "blockquote", "table", "thead", "tbody", "tr", "th", "td"},
        attributes={"a": ["href", "title", "rel"]},
        protocols={"http", "https", "mailto"},
    )
    return mark_safe(cleaned)


@register.filter
def filesize(value):
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
