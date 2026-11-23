"""GitHub repozitoriyning arxivini (snapshot) yuklab olish — ko'rib chiqish va plagiat tekshiruvi uchun."""
import re

import requests

REPO_RE = re.compile(r"^https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/.*)?$", re.IGNORECASE)
MAX_BYTES = 25 * 1024 * 1024


def parse_repo(url):
    match = REPO_RE.match((url or "").strip())
    return (match.group(1), match.group(2)) if match else None


def fetch_snapshot(url, max_bytes=MAX_BYTES):
    """(zip_baytlari, xato). Faqat ochiq (public) repozitoriylar uchun ishlaydi."""
    parsed = parse_repo(url)
    if not parsed:
        return None, "Havola GitHub repozitoriysi formatida emas."
    owner, repo = parsed
    try:
        resp = requests.get(f"https://codeload.github.com/{owner}/{repo}/zip/HEAD", stream=True, timeout=(5, 25))
    except requests.RequestException:
        return None, "GitHub bilan bog'lanib bo'lmadi — havola saqlandi, kodni GitHub orqali ko'ring."
    if resp.status_code == 404:
        return None, "Repozitoriy topilmadi yoki yopiq (private) — havola saqlandi."
    if resp.status_code != 200:
        return None, f"GitHub xatosi ({resp.status_code}) — havola saqlandi."
    data, size = [], 0
    for chunk in resp.iter_content(1024 * 256):
        size += len(chunk)
        if size > max_bytes:
            return None, "Repozitoriy juda katta — havola saqlandi."
        data.append(chunk)
    return b"".join(data), ""
