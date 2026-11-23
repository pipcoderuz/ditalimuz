from django import template
from django.utils.safestring import mark_safe

from design.dynamic import build_standalone_form
from design.models import SiteBlock

register = template.Library()


@register.simple_tag(takes_context=True)
def render_blocks(context, placement):
    """{% render_blocks 'landing' %} — shu joydagi faol, foydalanuvchiga ko'rinadigan bloklarni chizadi."""
    from django.template.loader import render_to_string

    request, user = context["request"], context["request"].user
    blocks = [b for b in SiteBlock.objects.filter(placement=placement, is_active=True).select_related("form").prefetch_related("items")
              if b.is_live() and b.visible_to(user)]
    out = []
    for block in blocks:
        ctx = {"block": block, "request": request, "user": user, "theme": context.get("theme")}
        if block.block_type == SiteBlock.Type.STATS:
            from accounts.models import User
            from courses.models import Course
            ctx["stats"] = {
                "courses": Course.objects.filter(is_published=True).count(),
                "students": User.objects.filter(role="student").count(),
                "teachers": User.objects.filter(role="teacher", approval_status="approved").count(),
            }
        if block.block_type == SiteBlock.Type.FORM and block.form_id and block.form.is_active:
            ctx["dyn_form"] = build_standalone_form(block.form)
        out.append(render_to_string(f"design/blocks/{block.block_type}.html", ctx, request=request))
    return mark_safe("".join(out))
