"""ZIP arxivdan manba kodlarni xavfsiz o'qish (diskka ochmasdan, xotirada)."""
import hashlib
import zipfile

TEXT_EXT = {
    ".py", ".java", ".js", ".jsx", ".ts", ".tsx", ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".go", ".rs", ".php",
    ".rb", ".kt", ".swift", ".dart", ".html", ".css", ".scss", ".sql", ".sh", ".json", ".xml", ".yml", ".yaml",
    ".md", ".txt", ".vue", ".lua", ".r",
}
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".idea", ".vscode", "target", "bin", "obj"}
MAX_FILES = 400
MAX_FILE_BYTES = 200_000
MAX_TOTAL_BYTES = 5_000_000


def sha256_of(fileobj):
    h = hashlib.sha256()
    for chunk in iter(lambda: fileobj.read(1024 * 1024), b""):
        h.update(chunk)
    fileobj.seek(0)
    return h.hexdigest()


def read_sources(fileobj, strip_root=False):
    """[(yo'l, matn), ...] ro'yxati. Katta/binar fayllar va keraksiz papkalar o'tkazib yuboriladi.

    strip_root=True faqat GitHub arxivlari uchun: ular bitta umumiy papka (repo-HEAD/) ichida keladi."""
    items, total = [], 0
    try:
        with zipfile.ZipFile(fileobj) as zf:
            for info in zf.infolist():
                if info.is_dir() or len(items) >= MAX_FILES:
                    continue
                parts = info.filename.split("/")
                if ".." in parts or info.filename.startswith("/") or any(p in SKIP_DIRS for p in parts):
                    continue
                name = parts[-1]
                ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext not in TEXT_EXT or info.file_size > MAX_FILE_BYTES:
                    continue
                total += info.file_size
                if total > MAX_TOTAL_BYTES:
                    break
                items.append((info.filename, zf.read(info).decode("utf-8", errors="replace")))
    except (zipfile.BadZipFile, OSError):
        return []
    if strip_root and items and all("/" in p for p, _ in items):
        first = items[0][0].split("/")[0]
        if all(p.split("/")[0] == first for p, _ in items):
            items = [(p.split("/", 1)[1], t) for p, t in items]
    return sorted(items)


def submission_sources(submission):
    if not submission.zip_file:
        return []
    try:
        submission.zip_file.open("rb")
        try:
            return read_sources(submission.zip_file, strip_root=submission.method == "github")
        finally:
            submission.zip_file.close()
    except (OSError, ValueError):
        return []
