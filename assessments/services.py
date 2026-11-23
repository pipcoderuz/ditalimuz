from community.notify import notify
from gamification import services as gamification

from . import codeutils, plagiarism


def process_submission(sub):
    """Yangi topshiriqdan keyingi ishlar: fingerprint, plagiat tekshiruvi, yutuqlar, o'qituvchiga bildirishnoma."""
    if sub.zip_file:
        sub.fingerprint = plagiarism.make_fingerprint(codeutils.submission_sources(sub))
        sub.save(update_fields=["fingerprint"])
        plagiarism.check_submission(sub)
    gamification.after_submission(sub)
    notify(
        sub.assignment.course.teacher,
        f"{sub.student.display_name} «{sub.assignment.title}» topshirig'ini yubordi.",
        sub.get_absolute_url(),
    )
