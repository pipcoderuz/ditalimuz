from .models import NavItem, SiteBlock, SiteTheme


def site(request):
    """Barcha shablonlar uchun: tema, navbar daraxti, e'lon va pastki qism bloklari."""
    theme = SiteTheme.get()
    user = request.user
    items = [i for i in NavItem.objects.filter(is_active=True).select_related("parent") if i.visible_to(user)]
    top = [i for i in items if i.parent_id is None]
    for item in top:
        item.visible_children = [c for c in items if c.parent_id == item.id]
    blocks = [b for b in SiteBlock.objects.filter(placement__in=["banner", "footer"], is_active=True).prefetch_related("items")
              if b.is_live() and b.visible_to(user)]
    return {
        "theme": theme,
        "theme_palette": theme.palette(),
        "nav_items": top,
        "banner_blocks": [b for b in blocks if b.placement == "banner"],
        "footer_blocks": [b for b in blocks if b.placement == "footer"],
    }
