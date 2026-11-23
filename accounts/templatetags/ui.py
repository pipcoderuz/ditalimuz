from django import template
from django.utils.safestring import mark_safe

from accounts import richtext

register = template.Library()


@register.filter
def rich(value):
    """{{ topic.content|rich }} — xavfsiz, kodlari ranglangan HTML."""
    return richtext.render_rich(value)


@register.filter
def excerpt(value, words=25):
    return richtext.excerpt(value, int(words))


@register.filter
def code_html(code, language="python"):
    return mark_safe(richtext.highlight_block(code or "", language or None))


@register.filter
def initial_of(value):
    return (str(value) or "?")[:1].upper()


@register.filter
def pct(value, total):
    """Foiz (butun son); total=0 bo'lsa 0."""
    try:
        return round(float(value) / float(total) * 100) if float(total) else 0
    except (TypeError, ValueError):
        return 0


@register.simple_tag
def flash_classes(tag):
    return {
        "success": "bg-green-50 text-green-800 border-green-200 dark:bg-green-900/30 dark:text-green-300 dark:border-green-800",
        "error": "bg-red-50 text-red-800 border-red-200 dark:bg-red-900/30 dark:text-red-300 dark:border-red-800",
        "warning": "bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-800",
    }.get(tag, "bg-blue-50 text-blue-800 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-800")
