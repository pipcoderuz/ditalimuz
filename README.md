# di-talim.uz — LMS platformasi (Django · Tailwind · Flowbite · Channels)

Dasturlashni o'rgatish va kasbiy kompetensiyalarni baholash LMS'i: progressiv o'qitish, avtomatik testlar,
rubrikali baholash, code review, plagiat nazorati, **real-time chat**, statistika, gamifikatsiya, sertifikat
va **kodsiz boshqariladigan dizayn**.

## Ishga tushirish (development)

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo        # demo kurs, foydalanuvchilar, chat yozishmasi (ixtiyoriy)
python manage.py runserver        # ASGI (Daphne) — WebSocket/chat shu bilan ishlaydi
```

http://127.0.0.1:8000 · Demo hisoblar (faqat sinov uchun, production'da o'zgartiring):
`admin/admin12345` · `teacher/teacher12345` · `student1…student5/student12345` · `teacher2` (tasdiq kutayotgan o'qituvchi).

> **Oldingi versiyadan o'tish:** migratsiyalar ketma-ket (`python manage.py migrate`). Eski DM (`Message`) yangi chatga
> ko'chirilmaydi; mavjud yozilishlar uchun «kursni boshlagan vaqt» faoliyatdan avtomatik tiklanadi.
> Toza boshlash uchun `db.sqlite3` ni o'chirib, `migrate` va `seed_demo` ni qayta ishga tushiring.

## Sakkiz talab qanday bajarilgan

1. **Real-time chat** — WebSocket (Django Channels). Xabar sahifani yangilamasdan darhol ko'rinadi (sinovda ikki brauzer
   orasida ≈0,1 s). Boshqa sahifada bo'lganda ham jonli bildirishnoma (toast) va navbar hisoblagichi. WebSocket uzilsa —
   avtomatik HTTP zaxira yo'li (3 s) va qayta ulanish. Xabarlar oddiy matn (HTML sifatida ishlamaydi).
2. **Dizayn** — Tailwind CSS 3 + Flowbite, yorug'/qorong'i rejim, mobil moslashuv (91 sahifa 390 px kenglikda tekshirilgan).
   Admin paneli — **django-unfold** (siz «django-fold» deganda shuni nazarda tutgan bo'lsangiz kerak).
   **Kodlar highlight qilinadi**: code review'da (Pygments, qatorma-qator, ko'p qatorli docstring ham to'g'ri), mavzu matnidagi
   kod bloklarida va test savollaridagi kod parchalarida.
3. **Admin orqali kodsiz dizayn** (`Boshqaruv → Dizayn markazi`, Unfold): sayt nomi/logotip/favicon/**asosiy rang**/qorong'i rejim;
   **navbar elementlari** (qo'shish, o'chirish, tartiblash, ochiladigan menyu, ichki sahifa yoki havola, kimga ko'rinishi,
   xabar hisoblagichi); **sahifa bloklari** (hero, kartalar, matn, bosqichlar, savol-javob, statistika, chaqiruv, e'lon, forma —
   bosh sahifa, panel, tepa e'lon va pastki qismda; kimga va qaysi vaqtda ko'rinishi); **forma elementlari** — mustaqil
   formalar (`/forma/<slug>/`), shuningdek ro'yxatdan o'tish va profil formalariga qo'shimcha maydonlar (matn, son, sana,
   ro'yxat, ko'p tanlov, belgi…; talaba/o'qituvchi uchun alohida majburiylik). Javoblar admin panelida.
4. **Umumiy statistika** menyusi (`/statistika/`, navbarda): admin — butun platforma, o'qituvchi — o'z kurslari, talaba — shaxsiy.
   Kartalar, oylar bo'yicha grafik, kurslar jadvali, talabalar jadvali, filtrlar (kurs, **kursni boshlagan sana oralig'i**, holat),
   CSV (Excel) eksport. Har bir talaba uchun batafsil sahifa: yozilgan → **boshlagan** → modullar bo'yicha yo'l → yakunlagan.
5. **Kurs va modul sanalari ixtiyoriy.** Sana qo'ymasangiz — kurs doim ochiq. Statistika uchun muhim bo'lgani — talaba
   kursni **qachon boshlagani** (`started_at`: birinchi faoliyat — mavzu, test, topshiriq) va oxirgi faoliyati.
6. **Rich text editor** — TipTap 3 (MIT, bepul): sarlavha, ro'yxat, jadval, kod bloki (til tanlash bilan), rasm yuklash/joylash,
   YouTube, havola, tekislash, belgilash. Sayt va admin panelida ishlaydi. Kiritilgan HTML **tozalanadi** (nh3): `<script>`,
   `onclick`, `javascript:`, begona iframe va xavfli `style` olib tashlanadi — saqlashda ham, ko'rsatishda ham.
7. **Kurs yakuni**: yakuniy **test**, yakuniy **loyiha**, **ikkalasi** yoki **hech biri** — qaysi birini qo'shsangiz, shu(lar)dan
   o'tilganda kurs yakunlanadi va sertifikat beriladi (ikkalasi bo'lsa — natijalar o'rtachasi). Hech biri bo'lmasa — barcha
   modullar tugagach.
8. **Mavzu ichida test, topshiriq va savol** (ochiq savol: matnli javob, o'qituvchi qo'lda baholaydi). Talaba mavzu sahifasida
   har biri bo'yicha **bahosini ko'radi** («Mening baholarim») va **shu yerning o'zida chatda yozishadi**. Majburiy elementlardan
   o'tmaguncha mavzuni tugatib bo'lmaydi. **Chat kimga borishini admin belgilaydi**: `Boshqaruv → Chat yo'naltirish` — har kurs
   uchun javobgar o'qituvchi/adminlar (bo'sh qolsa — kurs o'qituvchisi). Chatni butunlay o'chirish ham mumkin.

Oldingi talablar (progressiv o'qitish va uning admin tugmasi, kirish testi, rubrika, code review, ZIP/GitHub topshirish,
plagiat, o'sish analitikasi, nishonlar, reyting, forum, bildirishnomalar, o'qituvchini tasdiqlash, sertifikat, read-only) saqlangan.

## Production

```bash
# .env: DEBUG=False, SECRET_KEY=<uzun kalit>, ALLOWED_HOSTS=di-talim.uz, CSRF_TRUSTED_ORIGINS=https://di-talim.uz,
#       DB_* (PostgreSQL), REDIS_URL=redis://localhost:6379/0
python manage.py migrate && python manage.py collectstatic --noinput
daphne -b 0.0.0.0 -p 8000 config.asgi:application      # HTTP + WebSocket
```
- **Redis majburiy** (bir nechta jarayon/server bo'lsa chat shu orqali ishlaydi). Redis'siz faqat bitta jarayonda ishlaydi.
- Static fayllarni WhiteNoise beradi. `media/` (avatar, topshiriq, rasmlar) — nginx orqali.
- Nginx'da WebSocket'ni o'tkazing: `proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade";`
- HTTPS yoqing (`DEBUG=False` da yo'naltirish va HSTS yoqiladi).

## Frontend (Tailwind/Flowbite/editor) qayta yig'ish — ixtiyoriy
Yig'ilgan fayllar `static/dist/` da tayyor, Node kerak emas. Shablonga yangi Tailwind klass qo'shsangiz:
```bash
npm install && npm run build      # tailwind.css, app.js, rich-editor.js, flowbite, chart.js
```
Asosiy rang CSS o'zgaruvchilari (`--p-50…950`) orqali admin tomonidan beriladi — uni o'zgartirish uchun qayta yig'ish kerak emas.

## Qabul qilingan qarorlar
- Chat javobgarlari kursga biriktiriladi (talaba → kurs javobgarlari). Admin hamma chatni ko'ra oladi; javobgar etib
  tayinlanmagan (hatto kurs o'qituvchisi ham) kirmaydi.
- Mavzu darajasidagi element «majburiy» belgilansa, mavzuni tugatish uchun undan o'tish shart (progressiv rejimda).
- Ochiq savol: bitta javob; o'tmagan bo'lsa qayta yuborsa baho tozalanadi; o'tgandan keyin o'zgartirib bo'lmaydi.
- «Kursni boshlagan» = birinchi talaba faoliyati (o'qituvchining ko'rishi hisoblanmaydi).
- Statistikadagi «boshqa talabalar o'rtachasi» — talabaning o'zi hisobga olinmaydi.

## Testlar
`python manage.py test tests` — 323 ta test (chat WebSocket'lari, xavfsizlik, ruxsatlar, statistika, dizayn builder va boshqalar).
Bo'lib ishga tushirish: `tests.test_chat`, `tests.test_design`, `tests.test_stats`, …
