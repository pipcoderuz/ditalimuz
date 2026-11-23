"""Kirish qoidalari: ixtiyoriy sanalar, kirish testi, progressiv o'qitish, mavzu elementlari, yakuniy bosqich va read-only.

Qoidalar qisqacha:
  * O'qituvchi/administrator uchun cheklov yo'q.
  * Kurs va modul sanalari IXTIYORIY: sana berilmasa, cheklov ham yo'q. Berilgan bo'lsa — kurs boshlanmaguncha kontent yopiq,
    tugash sanasidan keyin kurs "faqat ko'rish" rejimiga o'tadi.
  * Kirish testi (pre-test) bo'lsa, u topshirilmaguncha modullar yopiq.
  * Progressiv o'qitish YOQILGAN bo'lsa:
      - mavzu: oldingi mavzu tugatilmaguncha yopiq; mavzuni tugatish uchun mavzuning MAJBURIY test/topshiriq/savollaridan o'tish kerak;
      - modul: oldingi modullar tugatilmaguncha yopiq (muddatidan oldin ham ochilishi mumkin);
      - yakuniy test/loyiha: barcha modullar tugagach ochiladi.
  * O'CHIRILGAN bo'lsa: modul (sanasi berilgan bo'lsa) o'z sanasida ochiladi, ichidagi hamma narsa erkin.
  * Kurs yakunlangan yoki tugash sanasi o'tgan bo'lsa — read-only: materiallar ochiq, topshirish bloklangan.
"""
from collections import defaultdict

from django.utils import timezone

from accounts.models import PlatformSettings
from assessments.models import Assignment, Attempt, OpenAnswer, OpenQuestion, Quiz, Submission

from .models import Enrollment, TopicProgress


class Access:
    __slots__ = ("allowed", "reason")

    def __init__(self, allowed, reason=""):
        self.allowed, self.reason = allowed, reason

    def __bool__(self):
        return self.allowed


OK = Access(True)


class CourseState:
    def __init__(self, user, course):
        self.user, self.course = user, course
        self.today = timezone.localdate()
        self.staff = user.can_teach
        self.enrollment = None if self.staff else Enrollment.objects.filter(course=course, student=user).first()
        self.progressive = PlatformSettings.get().progressive_learning
        self.modules = list(course.modules.prefetch_related("topics"))
        self._module_by_id = {m.id: m for m in self.modules}
        self._topic_by_id = {t.id: t for m in self.modules for t in m.topics.all()}
        self.pretest = course.quizzes.filter(kind=Quiz.Kind.PRETEST).first()
        self.final_quiz = course.quizzes.filter(kind=Quiz.Kind.FINAL).first()
        self.final_assignment = course.assignments.filter(kind=Assignment.Kind.FINAL).first()

        self.done_topics, self.passed_quizzes, self.passed_assignments, self.passed_questions = set(), set(), set(), set()
        self.pretest_done = self.pretest is None
        if not self.staff:
            self.done_topics = set(TopicProgress.objects.filter(student=user, topic__module__course=course).values_list("topic_id", flat=True))
            self.passed_quizzes = set(Attempt.objects.filter(student=user, quiz__course=course, passed=True).values_list("quiz_id", flat=True))
            self.passed_assignments = set(
                Submission.objects.filter(student=user, assignment__course=course, passed=True).values_list("assignment_id", flat=True)
            )
            self.passed_questions = set(
                OpenAnswer.objects.filter(student=user, question__course=course, passed=True).values_list("question_id", flat=True)
            )
            if self.pretest:
                self.pretest_done = Attempt.objects.filter(quiz=self.pretest, student=user).exists()

        # majburiy elementlar: modul darajasida va mavzu darajasida
        self._mod_quizzes, self._mod_assignments = defaultdict(list), defaultdict(list)
        self._top_quizzes, self._top_assignments, self._top_questions = defaultdict(list), defaultdict(list), defaultdict(list)
        for q in course.quizzes.filter(required=True):
            if q.kind == Quiz.Kind.MODULE:
                self._mod_quizzes[q.module_id].append(q.id)
            elif q.kind == Quiz.Kind.TOPIC:
                self._top_quizzes[q.topic_id].append(q.id)
        for a in course.assignments.filter(required=True):
            if a.kind == Assignment.Kind.MODULE:
                self._mod_assignments[a.module_id].append(a.id)
            elif a.kind == Assignment.Kind.TOPIC:
                self._top_assignments[a.topic_id].append(a.id)
        for oq in course.open_questions.filter(required=True):
            self._top_questions[oq.topic_id].append(oq.id)

    # ----- holat -----
    @property
    def enrolled(self):
        return self.enrollment is not None

    @property
    def read_only(self):
        if not self.enrollment:
            return False
        ended = self.course.end_date is not None and self.today > self.course.end_date
        return self.enrollment.status == Enrollment.Status.COMPLETED or ended

    @property
    def can_act(self):
        """Talaba test/topshiriq topshira oladimi (read-only emas)."""
        return self.enrolled and not self.read_only

    def topic_items_done(self, topic):
        """Mavzuning majburiy test/topshiriq/savollaridan o'tilganmi."""
        return (
            all(q in self.passed_quizzes for q in self._top_quizzes[topic.id])
            and all(a in self.passed_assignments for a in self._top_assignments[topic.id])
            and all(q in self.passed_questions for q in self._top_questions[topic.id])
        )

    def topics_done(self, module):
        return all(t.id in self.done_topics for t in module.topics.all())

    def module_passed(self, module):
        return (
            self.topics_done(module)
            and all(q in self.passed_quizzes for q in self._mod_quizzes[module.id])
            and all(a in self.passed_assignments for a in self._mod_assignments[module.id])
        )

    def all_modules_passed(self):
        return all(self.module_passed(m) for m in self.modules)

    # ----- kirish tekshiruvlari -----
    def _base(self):
        """None — to'siq yo'q; Access — natija aniq (ruxsat yoki rad)."""
        if self.staff:
            return OK
        if not self.enrolled:
            return Access(False, "Avval kursga yoziling.")
        if self.read_only:
            return OK
        if self.course.start_date and self.today < self.course.start_date:
            return Access(False, f"Kurs {self.course.start_date:%d.%m.%Y} sanasida boshlanadi.")
        return None

    def module_access(self, module):
        module = self._module_by_id.get(module.id, module)
        base = self._base()
        if base is not None:
            return base
        if not self.pretest_done:
            return Access(False, "Avval kirish testini (pre-test) topshiring.")
        if self.progressive:
            idx = self.modules.index(module)
            if not all(self.module_passed(m) for m in self.modules[:idx]):
                return Access(False, "Oldingi modulni tugatib, o'tish ballini olishingiz kerak.")
            return OK
        if module.start_date and self.today < module.start_date:
            return Access(False, f"Bu modul {module.start_date:%d.%m.%Y} sanasida ochiladi.")
        return OK

    def topic_access(self, topic):
        topic = self._topic_by_id.get(topic.id, topic)
        module = self._module_by_id.get(topic.module_id, topic.module)
        acc = self.module_access(module)
        if not acc or self.staff or self.read_only or not self.progressive:
            return acc
        topics = list(module.topics.all())
        idx = next(i for i, t in enumerate(topics) if t.id == topic.id)
        if idx > 0 and topics[idx - 1].id not in self.done_topics:
            return Access(False, "Avval oldingi mavzuni tugating.")
        return OK

    def final_access(self):
        base = self._base()
        if base is not None:
            return base
        if not self.pretest_done:
            return Access(False, "Avval kirish testini (pre-test) topshiring.")
        if self.progressive and not self.all_modules_passed():
            return Access(False, "Yakuniy bosqich barcha modullarni tugatgandan keyin ochiladi.")
        return OK

    def _module_level(self, module):
        module = self._module_by_id.get(module.id, module)
        acc = self.module_access(module)
        if not acc or self.staff or self.read_only or not self.progressive:
            return acc
        if not self.topics_done(module):
            return Access(False, "Avval modulning barcha mavzularini tugating.")
        return OK

    def quiz_access(self, quiz):
        if quiz.kind == Quiz.Kind.PRETEST:
            base = self._base()
            return base if base is not None else OK
        if quiz.kind == Quiz.Kind.TOPIC:
            return self.topic_access(quiz.topic)
        if quiz.kind == Quiz.Kind.FINAL:
            return self.final_access()
        return self._module_level(quiz.module)

    def assignment_access(self, assignment):
        if assignment.kind == Assignment.Kind.FINAL:
            return self.final_access()
        if assignment.kind == Assignment.Kind.TOPIC:
            return self.topic_access(assignment.topic)
        return self._module_level(assignment.module)

    def open_question_access(self, question):
        return self.topic_access(question.topic)
