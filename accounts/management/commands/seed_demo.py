"""Demo ma'lumotlar: python manage.py seed_demo"""
import hashlib
import io
import zipfile
from datetime import date, timedelta

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User
from assessments.grading import grade_quiz
from assessments.models import (
    Assignment, Choice, OpenAnswer, OpenQuestion, Question, Quiz, RubricCriterion, Submission, SubmissionScore,
)
from community import chat
from assessments.services import process_submission
from courses.models import Competency, Course, Enrollment, Module, Topic, TopicProgress
from gamification import services as gamification


def make_zip(code):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("project/main.py", code)
        zf.writestr("project/README.md", "# Loyiha\n")
    return buf.getvalue()


BANK_CODE = '''class BankAccount:
    def __init__(self, owner, balance=0):
        self.owner = owner
        self.balance = balance
        self.history = []

    def deposit(self, amount):
        if amount <= 0:
            raise ValueError("Summa musbat bo'lishi kerak")
        self.balance += amount
        self.history.append(("deposit", amount))

    def withdraw(self, amount):
        if amount > self.balance:
            raise ValueError("Mablag' yetarli emas")
        self.balance -= amount
        self.history.append(("withdraw", amount))

    def report(self):
        for kind, value in self.history:
            print(kind, value)
        return self.balance


def main():
    account = BankAccount("Ali", 100)
    account.deposit(50)
    account.withdraw(30)
    print(account.report())


main()
'''
# Xuddi shu kod, faqat o'zgaruvchi nomlari almashtirilgan (plagiat namunasi)
BANK_CODE_RENAMED = (
    BANK_CODE.replace("BankAccount", "Hisob").replace("owner", "egasi").replace("balance", "qoldiq")
    .replace("history", "tarix").replace("amount", "summa").replace("account", "hisob1")
    .replace("kind", "tur").replace("value", "qiymat")
)
OTHER_CODE = '''import random

def guess_game(limit):
    secret = random.randint(1, limit)
    attempts = 0
    while True:
        attempts += 1
        guess = int(input("Taxmin: "))
        if guess == secret:
            return attempts
        elif guess < secret:
            print("Kattaroq")
        else:
            print("Kichikroq")

print(guess_game(100))
'''


class Command(BaseCommand):
    help = "Demo foydalanuvchilar, kurs, testlar, topshiriqlar va namunaviy ma'lumotlarni yaratadi"

    def handle(self, *args, **options):
        today = date.today()

        def user(username, password, role, first, last, approval="approved"):
            u, created = User.objects.get_or_create(
                username=username,
                defaults={"role": role, "first_name": first, "last_name": last, "approval_status": approval,
                          "email": f"{username}@di-talim.uz"},
            )
            if created:
                u.set_password(password)
                u.save()
            return u

        user("admin", "admin12345", "admin", "Admin", "Administrator")
        teacher = user("teacher", "teacher12345", "teacher", "Aziz", "Karimov")
        user("teacher2", "teacher12345", "teacher", "Zilola", "Ergasheva", approval="pending")
        students = [
            user(f"student{i}", "student12345", "student", n, s)
            for i, (n, s) in enumerate(
                [("Ali", "Valiyev"), ("Malika", "Rahimova"), ("Jasur", "Tursunov"), ("Dilnoza", "Sobirova"), ("Bekzod", "Aliyev")],
                start=1,
            )
        ]

        course, created = Course.objects.get_or_create(
            slug="python-asoslari",
            defaults={"title": "Python dasturlash asoslari", "teacher": teacher, "start_date": today - timedelta(days=14),
                      "end_date": today + timedelta(days=120),
                      "description": "Python tilini noldan o'rganing: o'zgaruvchilar, shartlar, sikllar, funksiyalar va OYD. Kurs oxirida katta loyiha va sertifikat."},
        )
        if not created:
            self.stdout.write("Demo kurs allaqachon mavjud — o'tkazib yuborildi.")
            return

        comps = {n: Competency.objects.create(course=course, name=n) for n in
                 ["Algoritmik fikrlash", "Sintaksis va ma'lumot turlari", "Xatolarni topish (debugging)"]}
        c_alg, c_syn, c_bug = comps.values()

        def module(title, order, start, end):
            return Module.objects.create(course=course, title=title, order=order, start_date=today + timedelta(days=start), end_date=today + timedelta(days=end))

        m1 = module("Python asoslari", 1, -14, 20)
        m2 = module("Funksiyalar va ma'lumotlar tuzilmalari", 2, 21, 55)
        m3 = module("Obyektga yo'naltirilgan dasturlash", 3, 56, 100)

        topics = {}
        for m, titles in [(m1, ["O'zgaruvchilar va turlar", "Shartli operatorlar", "Sikllar"]),
                          (m2, ["Funksiyalar", "Ro'yxat va lug'atlar"]), (m3, ["Sinflar va obyektlar", "Meros va polimorfizm"])]:
            for i, t in enumerate(titles, start=1):
                topics[t] = Topic.objects.create(
                    module=m, title=t, order=i,
                    content=f"«{t}» mavzusi bo'yicha nazariy material.\n\nBu yerda tushuntirish, kod namunalari va mashqlar bo'ladi.",
                    video_url="https://www.youtube.com/watch?v=kqtD5dpn9C8" if i == 1 else "",
                )

        def make_quiz(title, kind, module_obj, questions, **kw):
            quiz = Quiz.objects.create(course=course, module=module_obj, kind=kind, title=title, order=0, **kw)
            for n, (text, comp, choices, extra) in enumerate(questions, start=1):
                q = Question.objects.create(quiz=quiz, text=text, competency=comp, order=n, **extra)
                for ctext, ok in choices:
                    Choice.objects.create(question=q, text=ctext, is_correct=ok)
            return quiz

        pre = make_quiz("Kirish testi", "pretest", None, [
            ("Python'da butun son turi qanday nomlanadi?", c_syn, [("int", True), ("integer", False), ("num", False)], {}),
            ("range(3) qaysi qiymatlarni beradi?", c_alg, [("0, 1, 2", True), ("1, 2, 3", False), ("0, 1, 2, 3", False)], {}),
            ("Quyidagi koddagi xatoni toping: for i in range(3) print(i)", c_bug,
             [(":” (ikki nuqta) yetishmayapti", True), ("range noto'g'ri", False), ("print noto'g'ri", False)], {}),
            ("Ro'yxat elementlari yig'indisini qaysi funksiya beradi?", c_syn, [("sum()", True), ("add()", False), ("total()", False)], {}),
        ], max_score=100, pass_score=0, max_attempts=1)

        quiz1 = make_quiz("1-modul testi", "module", m1, [
            ("x = 5; x += 2; print(x) nimani chiqaradi?", c_syn, [("7", True), ("5", False), ("52", False)], {}),
            ("while sikli qachon to'xtaydi?", c_alg, [("Shart False bo'lganda", True), ("Doim", False), ("10 marta", False)], {}),
            ("print(10 // 3) natijasi?", c_syn, [("3", True), ("3.33", False), ("1", False)], {}),
            ("Kodda xato bor: if x = 5: print(x). Nima noto'g'ri?", c_bug, [("= o'rniga == bo'lishi kerak", True), ("print noto'g'ri", False)],
             {"is_bug_hunt": True, "code_snippet": "if x = 5:\n    print(x)"}),
            ("Kodda xato bor: for i in range(3):\nprint(i). Nima noto'g'ri?", c_bug, [("Satr boshida bo'shliq (indent) yo'q", True), ("range noto'g'ri", False)],
             {"is_bug_hunt": True, "code_snippet": "for i in range(3):\nprint(i)"}),
        ], max_score=100, pass_score=60, max_attempts=3)
        make_quiz("2-modul testi", "module", m2, [
            ("Funksiyadan qiymat qaytarish uchun nima ishlatiladi?", c_syn, [("return", True), ("yield only", False), ("print", False)], {}),
            ("Lug'at kaliti bo'yicha qiymat olish?", c_syn, [("d[key]", True), ("d.key()", False)], {}),
        ], max_score=50, pass_score=30)

        def assignment(title, module_obj, kind, desc, due_offset, criteria, pass_score=60):
            a = Assignment.objects.create(course=course, module=module_obj, kind=kind, title=title, description=desc,
                                          pass_score=pass_score, due_date=today + timedelta(days=due_offset))
            for name, description, mx in criteria:
                RubricCriterion.objects.create(assignment=a, name=name, description=description, max_score=mx)
            a.recalc_max_score()
            return a

        rubric = [("To'g'ri ishlashi", "Dastur talab qilingan natijani beradi", 40),
                  ("Kod tozaligi", "Nomlash, tuzilma, o'qilishi", 30), ("Xatoliklarni ushlash", "try/except, tekshiruvlar", 30)]
        a1 = assignment("Bank hisob-raqami dasturi", m1, "module", "BankAccount sinfini yozing: deposit, withdraw, report. Kodni ZIP sifatida yoki GitHub havolasi bilan topshiring.", 18, rubric)
        assignment("Kalkulyator", m2, "module", "Funksiyalar yordamida konsol kalkulyator yozing.", 50, rubric)
        assignment("Yakuniy loyiha: Kutubxona tizimi", None, "final", "OYD asosida kutubxona boshqaruv tizimini yarating (kitoblar, o'quvchilar, qarz berish).", 110, rubric, pass_score=60)

        # --- Talabalar faoliyati ---
        for st in students[:4]:
            Enrollment.objects.create(course=course, student=st)
        s1, s2, s3, s4 = students[:4]

        def take_pretest(st, correct_count):
            post = _Post()
            for i, q in enumerate(pre.questions.all()):
                right = [c.id for c in q.choices.all() if c.is_correct]
                wrong = [c.id for c in q.choices.all() if not c.is_correct]
                post.set(f"q_{q.pk}", right if i < correct_count else wrong[:1])
            grade_quiz(pre, st, post, timezone.now() - timedelta(minutes=3))

        take_pretest(s1, 1); take_pretest(s2, 2); take_pretest(s3, 2)

        # s1: 1-modulni to'liq tugatgan
        for t in ["O'zgaruvchilar va turlar", "Shartli operatorlar", "Sikllar"]:
            TopicProgress.objects.create(student=s1, topic=topics[t])
            gamification.after_topic_complete(s1, topics[t])
        post = _Post()
        for q in quiz1.questions.all():
            post.set(f"q_{q.pk}", [c.id for c in q.choices.all() if c.is_correct])
        gamification.after_attempt(grade_quiz(quiz1, s1, post, timezone.now() - timedelta(minutes=2)))
        # s2: 1-mavzu tugatgan, test hali yo'q
        TopicProgress.objects.create(student=s2, topic=topics["O'zgaruvchilar va turlar"])

        def submit(st, code, offset_min):
            sub = Submission(assignment=a1, student=st, method="zip", comment="Ishim shu")
            data = make_zip(code)
            sub.zip_file.save("project.zip", ContentFile(data), save=False)
            sub.zip_size, sub.zip_sha256 = len(data), hashlib.sha256(data).hexdigest()
            sub.save()
            process_submission(sub)
            return sub

        sub1 = submit(s1, BANK_CODE, 0)
        for crit, sc in zip(a1.criteria.all(), [36, 24, 27]):
            SubmissionScore.objects.create(submission=sub1, criterion=crit, score=sc, comment="")
        sub1.total_score, sub1.percent, sub1.passed, sub1.status = 87, 87.0, True, "graded"
        sub1.graded_by, sub1.graded_at, sub1.teacher_comment = teacher, timezone.now(), "Yaxshi ish, davom eting!"
        sub1.save()
        submit(s2, BANK_CODE_RENAMED, 5)   # s1 koddan nusxa (nomlari almashtirilgan) -> plagiat flagi
        submit(s3, OTHER_CODE, 9)          # mustaqil ish

        # --- Mavzu darajasidagi test va ochiq savol ---
        now = timezone.now()
        t_vars, t_cond = topics["O'zgaruvchilar va turlar"], topics["Shartli operatorlar"]
        topic_quiz = Quiz.objects.create(course=course, topic=t_vars, kind="topic", title="Mavzu testi: o'zgaruvchilar", max_score=100,
                                         pass_score=50, max_attempts=3, order=1)
        for n, (text, choices) in enumerate([
            ("Qaysi nom to'g'ri o'zgaruvchi nomi?", [("yosh_1", True), ("1yosh", False), ("yosh-1", False)]),
            ("x = '5' + '3' natijasi nima?", [("'53'", True), ("8", False), ("Xato", False)]),
        ], start=1):
            q = Question.objects.create(quiz=topic_quiz, text=text, competency=c_syn, order=n)
            for ctext, ok in choices:
                Choice.objects.create(question=q, text=ctext, is_correct=ok)
        for st in (s1, s2):
            post = _Post()
            for q in topic_quiz.questions.all():
                post.set(f"q_{q.pk}", [c.id for c in q.choices.all() if c.is_correct])
            grade_quiz(topic_quiz, st, post, now - timedelta(minutes=1))
        open_q = OpenQuestion.objects.create(
            course=course, topic=t_cond, max_score=10, pass_score=6,
            text="<p>Ikki sonning kattasini topadigan <strong>if / else</strong> kodini yozing va qisqacha tushuntiring.</p>")
        OpenAnswer.objects.create(question=open_q, student=s1, text="if a > b:\n    print(a)\nelse:\n    print(b)", status="graded", score=9,
                                  passed=True, feedback="To'g'ri! max() funksiyasi bilan ham yozish mumkinligini eslang.",
                                  graded_by=teacher, graded_at=now)

        # --- Kurs yakuni: yakuniy test + yakuniy loyiha (ikkalasi ham majburiy) ---
        make_quiz("Yakuniy test", "final", None, [
            ("Funksiya qanday e'lon qilinadi?", c_syn, [("def nom():", True), ("function nom()", False), ("fun nom:", False)], {}),
            ("Ro'yxatning oxiriga element qo'shish?", c_syn, [("append()", True), ("add()", False), ("push_back()", False)], {}),
            ("Quyidagi sikl nechta marta ishlaydi? for i in range(2, 6)", c_alg, [("4", True), ("5", False), ("6", False)], {}),
        ], max_score=100, pass_score=60, max_attempts=2)

        # --- Real-time chat: mavzu bo'yicha talaba ↔ javobgar ---
        room = chat.topic_room(t_vars, s1)
        for sender, text in [
            (s1, "Assalomu alaykum! O'zgaruvchi nomlari haqida savolim bor."),
            (teacher, "Va alaykum assalom! Eshitaman, qaysi qoidalar tushunarsiz?"),
            (s1, "Nom raqam bilan boshlanishi mumkinmi?"),
            (teacher, "Yo'q. Nom harf yoki _ bilan boshlanishi kerak, masalan: yosh_1."),
        ]:
            chat.send_message(room, sender, text)

        # --- Talabalar kursni qachon boshlagani (statistika uchun) ---
        for st, (enrolled, started, last) in {s1: (14, 12, 0), s2: (8, 5, 1), s3: (5, 3, 2), s4: (2, None, None)}.items():
            Enrollment.objects.filter(course=course, student=st).update(
                enrolled_at=now - timedelta(days=enrolled),
                started_at=now - timedelta(days=started) if started is not None else None,
                last_activity_at=now - timedelta(days=last) if last is not None else None)

        # --- Ikkinchi kurs: sanalarsiz (boshlanish/tugash sanasi ixtiyoriy ekanini ko'rsatadi) ---
        web = Course.objects.create(
            slug="veb-dasturlash", title="Veb dasturlash (sanasiz kurs)", teacher=teacher,
            description="<p>Bu kursning <strong>boshlanish va tugash sanasi yo'q</strong> — talaba xohlagan paytda boshlaydi.</p>")
        web_mod = Module.objects.create(course=web, title="HTML va CSS", order=1)
        web_topics = [Topic.objects.create(module=web_mod, title=t, order=i, content=f"<h2>{t}</h2><p>Mavzu matni.</p>") for i, t in enumerate(["HTML tuzilmasi", "CSS asoslari"], start=1)]
        OpenQuestion.objects.create(course=web, topic=web_topics[0], max_score=10, pass_score=6, text="<p>Semantik teg nima va nima uchun kerak?</p>")
        Enrollment.objects.create(course=web, student=students[4])

        self.stdout.write(self.style.SUCCESS("Demo ma'lumotlar tayyor."))
        self.stdout.write(
            "Kirish: admin/admin12345, teacher/teacher12345, student1..student5/student12345 "
            "(teacher2 — tasdiq kutayotgan o'qituvchi). Ishlab chiqarishda parollarni almashtiring!"
        )


class _Post:
    """grade_quiz() uchun request.POST o'rnini bosuvchi oddiy to'plam."""

    def __init__(self):
        self.data = {}

    def set(self, key, values):
        self.data[key] = [str(v) for v in values]

    def getlist(self, key):
        return self.data.get(key, [])
