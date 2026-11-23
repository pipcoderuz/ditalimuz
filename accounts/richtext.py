"""Rich text: xavfsiz HTML (nh3 bilan tozalash), Pygments bilan kod highlight, formalar uchun vidjet/maydon."""
import html as html_lib
import re

import nh3
from django import forms
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.utils.text import Truncator
from pygments import lex
from pygments.lexers import TextLexer, get_lexer_by_name, get_lexer_for_filename
from pygments.token import STANDARD_TYPES
from pygments.util import ClassNotFound

ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "code", "col", "colgroup", "div", "em", "h1", "h2", "h3", "h4", "hr", "i", "iframe", "img", "li",
    "mark", "ol", "p", "pre", "s", "span", "strong", "sub", "sup", "table", "tbody", "td", "th", "thead", "tr", "u", "ul",
}
ALLOWED_ATTRS = {
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"colspan", "rowspan"}, "th": {"colspan", "rowspan"},
    "code": {"class"}, "pre": {"class"},
    "iframe": {"src", "width", "height", "allowfullscreen"},
    "div": {"data-youtube-video"},
    "p": {"style"}, "h1": {"style"}, "h2": {"style"}, "h3": {"style"}, "h4": {"style"},
}
YOUTUBE_PREFIXES = ("https://www.youtube.com/embed/", "https://www.youtube-nocookie.com/embed/")
STYLE_RE = re.compile(r"^\s*text-align:\s*(left|center|right|justify)\s*;?\s*$", re.I)
CLASS_RE = re.compile(r"^language-[\w+#.-]{1,30}$")
LOOKS_LIKE_HTML = re.compile(r"<\s*(p|div|h[1-6]|ul|ol|li|pre|table|blockquote|br|img|iframe|strong|em|a|span)\b", re.I)


def _attribute_filter(tag, attr, value):
    """Xavfli qiymatlarni olib tashlaydi: faqat text-align stili, faqat language-* klass, faqat YouTube iframe."""
    if attr == "style":
        return value if STYLE_RE.match(value) else None
    if attr == "class":
        return value if CLASS_RE.match(value) else None
    if tag == "iframe" and attr == "src":
        return value if value.startswith(YOUTUBE_PREFIXES) else None
    if tag == "a" and attr == "target":
        return "_blank" if value == "_blank" else None
    return value


def clean_html(value):
    """Foydalanuvchi kiritgan HTML'ni tozalaydi (XSS'dan himoya). Ruxsat etilmagan teg/atributlar olib tashlanadi."""
    if not value:
        return ""
    cleaned = nh3.clean(
        value, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, attribute_filter=_attribute_filter,
        url_schemes={"http", "https", "mailto"}, link_rel="noopener noreferrer",
    )
    # src'i olib tashlangan (begona) iframe'lar ko'rinmas bo'sh qolmasin
    return re.sub(r"<iframe(?![^>]*\bsrc=)[^>]*>\s*</iframe>", "", cleaned)


# ------------------------------------------------------------------ Pygments
def _css_class(ttype):
    while ttype not in STANDARD_TYPES:
        ttype = ttype.parent
    return STANDARD_TYPES[ttype]


def _lexer(language=None, filename=None):
    opts = {"stripnl": False, "ensurenl": False}
    try:
        if language:
            return get_lexer_by_name(language, **opts)
        if filename:
            return get_lexer_for_filename(filename, **opts)
    except ClassNotFound:
        pass
    return TextLexer(**opts)


def highlight_lines(code, language=None, filename=None):
    """Kodni Pygments bilan ranglab, QATORLAR ro'yxati (HTML) sifatida qaytaradi.
    Ko'p qatorli tokenlar (docstring, izoh) qatorlar bo'yicha to'g'ri bo'linadi — har qator mustaqil, yopiq HTML."""
    code = code.replace("\r\n", "\n").replace("\r", "\n")
    lines = [[]]
    for ttype, value in lex(code, _lexer(language, filename)):
        cls = _css_class(ttype)
        for i, part in enumerate(value.split("\n")):
            if i:
                lines.append([])
            if part:
                lines[-1].append(f'<span class="{cls}">{escape(part)}</span>' if cls else escape(part))
    out = ["".join(parts) for parts in lines]
    if code.endswith("\n") and out and out[-1] == "":
        out.pop()
    return out


def highlight_block(code, language=None):
    inner = "\n".join(highlight_lines(code, language))
    return f'<pre class="hl"><code>{inner}</code></pre>'


_CODE_BLOCK_RE = re.compile(r'<pre(?:\s[^>]*)?><code(?:\s+class="language-([\w+#.-]+)")?>(.*?)</code></pre>', re.S)


def highlight_rich_html(html):
    """Tozalangan HTML ichidagi <pre><code class="language-x"> bloklarini serverda ranglaydi."""
    return _CODE_BLOCK_RE.sub(lambda m: highlight_block(html_lib.unescape(m.group(2)), m.group(1)), html)


def render_rich(value):
    """Rich text -> xavfsiz HTML. Eski (oddiy matnli) kontent ham to'g'ri ko'rsatiladi."""
    value = value or ""
    if not LOOKS_LIKE_HTML.search(value):
        paragraphs = [f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in re.split(r"\n{2,}", value.strip()) if p.strip()]
        return mark_safe("".join(paragraphs))
    return mark_safe(highlight_rich_html(clean_html(value)))


def excerpt(value, words=25):
    """HTML'dan oddiy matn ko'rinishidagi qisqa parcha (ro'yxatlar uchun)."""
    text = html_lib.unescape(nh3.clean(value or "", tags=set()))
    return Truncator(" ".join(text.split())).words(words)


# ------------------------------------------------------------------ Forma vidjeti
class RichTextarea(forms.Textarea):
    """textarea[data-rich] — sahifadagi editor skripti uni vizual editorga aylantiradi."""

    def __init__(self, attrs=None):
        base = {"data-rich": "1", "rows": 8}
        base.update(attrs or {})
        super().__init__(base)

    class Media:
        css = {"all": ("dist/rich-editor.css",)}
        js = ("dist/rich-editor.js",)


class RichTextFormField(forms.CharField):
    widget = RichTextarea

    def clean(self, value):
        return clean_html(super().clean(value))


class RichAdminMixin:
    """ModelAdmin uchun: rich_fields dagi TextField'lar vizual editor bilan tahrirlanadi."""

    rich_fields = ()

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name in self.rich_fields:
            return RichTextFormField(label=db_field.verbose_name.capitalize(), required=not db_field.blank, help_text=db_field.help_text)
        return super().formfield_for_dbfield(db_field, request, **kwargs)
