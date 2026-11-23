"""Sodda plagiat nazorati: ZIP hajmi, vaqti, o'zgaruvchi nomlari va kod tuzilmasi bo'yicha o'xshashlik.

Formula:
    ident  = o'zgaruvchi/funksiya nomlari to'plamlarining Jaccard o'xshashligi
    struct = nomlar normallashtirilgan (I) va sonlar (N) bilan almashtirilgan 5-token "shingle"lar Jaccard o'xshashligi
             (o'zgaruvchi nomi o'zgartirilgan nusxani ham ushlaydi)
    size   = min(hajm)/max(hajm) — ZIP fayl hajmlarining nisbati
    ball   = 100 * max( 0.4*ident + 0.5*struct + 0.1*size , 0.85*struct )
    ZIP fayllarning SHA-256 xeshi bir xil bo'lsa — 100%.
Yuborilgan vaqtlar orasidagi farq ham tafsilotlarda ko'rsatiladi (ball hisobiga kirmaydi).
"""
import re
import zlib

from django.urls import reverse

from accounts.models import PlatformSettings

from .models import PlagiarismFlag, Submission

KEYWORDS = set(
    """and as assert async await break case catch class const continue def default del do elif else enum except extends
    false final finally float for from function global goto if implements import in instanceof int interface is lambda let
    long namespace new none not null or package pass print private protected public raise return self short static string
    struct super switch synchronized this throw throws true try typeof using var void volatile while with yield main
    args string str list dict set tuple range len input output self cls bool char double byte boolean object System
    out println printf scanf cout cin std endl include define return""".lower().split()
)
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+|[^\sA-Za-z0-9_]")
COMMENT_RE = re.compile(r"/\*.*?\*/|//[^\n]*|#[^\n]*", re.S)
SHINGLE_N = 5
MAX_SHINGLES = 3000
MIN_SHINGLES = 20


def make_fingerprint(files):
    idents, shingles = set(), set()
    for _, text in files:
        tokens = TOKEN_RE.findall(COMMENT_RE.sub(" ", text))
        norm = []
        for tok in tokens:
            low = tok.lower()
            if tok[0].isalpha() or tok[0] == "_":
                if low in KEYWORDS:
                    norm.append(low)
                else:
                    norm.append("I")
                    if len(tok) >= 3:
                        idents.add(tok)
            elif tok[0].isdigit():
                norm.append("N")
            else:
                norm.append(tok)
        for i in range(len(norm) - SHINGLE_N + 1):
            shingles.add(zlib.crc32(" ".join(norm[i : i + SHINGLE_N]).encode()))
    return {"idents": sorted(idents)[:2000], "shingles": sorted(shingles)[:MAX_SHINGLES]}


def _jaccard(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a and b else 0.0


def compare(sub_a, sub_b):
    """(ball 0..100, tafsilotlar) yoki (0, None) — taqqoslab bo'lmasa."""
    if sub_a.zip_sha256 and sub_a.zip_sha256 == sub_b.zip_sha256:
        return 100.0, {"same_hash": True, "identifiers": 100.0, "structure": 100.0, "size": 100.0,
                       "time_diff_min": _minutes(sub_a, sub_b)}
    fa, fb = sub_a.fingerprint or {}, sub_b.fingerprint or {}
    if len(fa.get("shingles", [])) < MIN_SHINGLES or len(fb.get("shingles", [])) < MIN_SHINGLES:
        return 0.0, None
    ident = _jaccard(fa.get("idents", []), fb.get("idents", []))
    struct = _jaccard(fa["shingles"], fb["shingles"])
    big, small = max(sub_a.zip_size, sub_b.zip_size), min(sub_a.zip_size, sub_b.zip_size)
    size = small / big if big else 0.0
    score = 100 * max(0.4 * ident + 0.5 * struct + 0.1 * size, 0.85 * struct)
    return round(score, 1), {
        "same_hash": False,
        "identifiers": round(ident * 100, 1),
        "structure": round(struct * 100, 1),
        "size": round(size * 100, 1),
        "time_diff_min": _minutes(sub_a, sub_b),
    }


def _minutes(a, b):
    return int(abs((a.submitted_at - b.submitted_at).total_seconds()) // 60)


def check_submission(submission):
    """Yangi topshiriqni shu topshiriqdagi boshqa talabalar ishlari bilan solishtiradi. Yaratilgan flaglarni qaytaradi."""
    from community.notify import notify

    if not submission.zip_file:
        return []
    threshold = PlatformSettings.get().plagiarism_threshold
    others = (
        Submission.objects.filter(assignment=submission.assignment)
        .exclude(student=submission.student)
        .exclude(zip_file="")
        .order_by("student_id", "-submitted_at")
    )
    seen, flags = set(), []
    for other in others:
        if other.student_id in seen:  # har bir talabaning eng oxirgi ishi
            continue
        seen.add(other.student_id)
        score, details = compare(submission, other)
        if details is None or score < threshold:
            continue
        a, b = sorted([submission, other], key=lambda s: s.pk)
        flag, created = PlagiarismFlag.objects.update_or_create(
            submission_a=a, submission_b=b, defaults={"assignment": submission.assignment, "score": score, "details": details}
        )
        flags.append(flag)
        if created:
            teacher = submission.assignment.course.teacher
            notify(
                teacher,
                f"Plagiat ogohlantirishi: {submission.student.display_name} va {other.student.display_name} "
                f"kodlari {score:.0f}% o'xshash ({submission.assignment.title}).",
                reverse("assessments:plagiarism_list"),
            )
    return flags
