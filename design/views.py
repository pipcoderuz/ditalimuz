from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from accounts.models import User
from community.notify import notify

from .dynamic import PREFIX, build_standalone_form, serialize
from .models import FormDefinition, FormSubmission


def public_form(request, slug):
    """Admin tuzgan mustaqil forma: ko'rsatish va javobni saqlash."""
    form_def = get_object_or_404(FormDefinition, slug=slug, purpose=FormDefinition.Purpose.CUSTOM, is_active=True)
    form = build_standalone_form(form_def, request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        labels = {PREFIX + fd.key: fd.label for fd in form_def.fields.all()}
        data = {labels[name]: serialize(value) for name, value in form.cleaned_data.items()}
        user = request.user if request.user.is_authenticated else None
        FormSubmission.objects.create(form=form_def, user=user, data=data)
        if form_def.notify_admins:
            from django.urls import reverse
            for admin in User.objects.filter(role=User.Role.ADMIN, is_active=True):
                notify(admin, f"«{form_def.title}» formasiga yangi javob keldi.", reverse("admin:design_formsubmission_changelist"))
        messages.success(request, form_def.success_message)
        nxt = request.POST.get("next", "")
        if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(nxt)          # faqat shu saytning o'z manzili (open redirect'dan himoya)
        return redirect("design:public_form", slug=slug)
    return render(request, "design/public_form.html", {"form_def": form_def, "form": form})
