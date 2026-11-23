"""Standart navbar va bosh sahifa bloklari (admin keyin ularni kodsiz o'zgartiradi)."""
from django.db import migrations

NAV = [
    # label, icon, route, url, order, anonymous, student, teacher, admin, badge
    ("Imkoniyatlar", "✨", "", "/#imkoniyatlar", 1, True, False, False, False, ""),
    ("Kurslar", "📚", "courses:course_list", "", 2, False, True, True, True, ""),
    ("Statistika", "📊", "analytics:overview", "", 3, False, True, True, True, ""),
    ("Talabalarim", "🎓", "courses:my_students", "", 4, False, False, True, True, ""),
    ("Plagiat", "🛡️", "assessments:plagiarism_list", "", 5, False, False, True, True, ""),
    ("Forum", "💬", "community:thread_list", "", 6, False, True, True, True, ""),
    ("Xabarlar", "✉️", "community:inbox", "", 7, False, True, True, True, "messages"),
    ("Boshqaruv", "⚙️", "accounts:admin_panel", "", 8, False, False, False, True, ""),
]

FEATURES = [
    ("🧭", "Progressiv o'qitish", "Mavzudan mavzuga, moduldan modulga — o'zlashtirish asosida. Kirish testi boshlang'ich bilimingizni aniqlaydi."),
    ("⚙️", "Avtomatik baholash", "Testlar darhol tekshiriladi. Loyihalar rubrika bo'yicha qismlarga bo'lib baholanadi — qayerda ball yo'qotganingizni ko'rasiz."),
    ("💬", "Code Review", "O'qituvchi kodingizning aniq qatorlariga izoh yozadi va real-time chatda savollaringizga javob beradi."),
    ("📈", "Kompetensiyalar o'sishi", "Kirish testi va yakuniy natijangiz solishtiriladi — qaysi ko'nikma qanchaga o'sgani grafikda ko'rinadi."),
    ("🏆", "Yutuqlar va reyting", "«Bug hunter», «Fast coder», «Perfect score» nishonlari va kurs reyting doskasi sizni rag'batlantiradi."),
    ("🎓", "Avtomatik sertifikat", "Yakuniy bosqichdan o'tgach sertifikat avtomatik yaratiladi va uning haqiqiyligini istalgan kishi tekshira oladi."),
]


def create_defaults(apps, schema_editor):
    SiteTheme = apps.get_model("design", "SiteTheme")
    NavItem = apps.get_model("design", "NavItem")
    SiteBlock = apps.get_model("design", "SiteBlock")
    BlockItem = apps.get_model("design", "BlockItem")

    SiteTheme.objects.get_or_create(pk=1)
    if not NavItem.objects.exists():
        for label, icon, route, url, order, a, s, t, ad, badge in NAV:
            NavItem.objects.create(label=label, icon=icon, route=route, url=url, order=order, show_anonymous=a,
                                   show_student=s, show_teacher=t, show_admin=ad, badge=badge)
    if not SiteBlock.objects.exists():
        SiteBlock.objects.create(
            placement="landing", block_type="hero", style="primary", order=1,
            title="Dasturlashni o'rganing. Kasbiy kompetensiyangizni o'stiring.",
            subtitle="Bosqichma-bosqich kurslar, avtomatik testlar, o'qituvchidan kod bo'yicha sharhlar, real-time chat, yutuqlar va sertifikat — barchasi bir joyda.",
            button_label="Bepul ro'yxatdan o'tish", button_url="/accounts/register/",
            show_student=True, show_teacher=True, show_admin=True,
        )
        SiteBlock.objects.create(placement="landing", block_type="stats", style="plain", order=2, title="Platforma raqamlarda")
        features = SiteBlock.objects.create(
            placement="landing", block_type="features", style="plain", order=3,
            title="Nima uchun di-talim.uz?", subtitle="O'rganish jarayonining har bir bosqichi o'ylab ishlab chiqilgan",
        )
        for i, (icon, title, text) in enumerate(FEATURES, start=1):
            BlockItem.objects.create(block=features, icon=icon, title=title, text=text, order=i)
        SiteBlock.objects.create(
            placement="landing", block_type="cta", style="dark", order=4,
            title="Bugun boshlang", subtitle="Ro'yxatdan o'tib, birinchi kursingizga yoziling.",
            button_label="Ro'yxatdan o'tish", button_url="/accounts/register/",
        )


class Migration(migrations.Migration):
    dependencies = [("design", "0001_initial")]
    operations = [migrations.RunPython(create_defaults, migrations.RunPython.noop)]
