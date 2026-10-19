"""CV linter: consistency with profile.yaml, es/en parity, language, LaTeX hygiene, PDF state."""
import re
import subprocess
from collections import Counter
from pathlib import Path

from cv_profile import load_profile
from keywords import terms_in

BASE_DIR = Path(__file__).resolve().parent.parent
VERSIONS_DIR = BASE_DIR / "versions"

ES_MONTHS = {"Jan": "Ene", "Apr": "Abr", "Aug": "Ago", "Dec": "Dic"}
ES_STRONG = re.compile(r"\b(Actualidad|Presente|Experiencia|Habilidades|Educación|Proyectos|Perfil|Cursando|Auxiliar)\b")
EN_STRONG = re.compile(r"\b(Present|Experience|Skills|Education|Projects|Summary|Currently)\b")
ES_WORDS = re.compile(r"\b(el|la|los|las|con|para|por|una|un|del|mediante|desarrollé|implementé|diseñé)\b", re.I)
NUMBER_TOKEN = re.compile(r"\d(?:[\d.,]*\d)?(?:\\?%|M)?")
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*\\?%")


class Report:
    def __init__(self):
        self.issues = []

    def add(self, file, level, code, msg):
        self.issues.append({"file": str(file), "level": level, "code": code, "message": msg})


def _plain(tex: str) -> str:
    for src, dst in ((r"\&", "&"), (r"\%", "%"), (r"\_", "_"), (r"\#", "#"), (r"\textbar", "|")):
        tex = tex.replace(src, dst)
    return tex


def _body(tex: str) -> str:
    """Document body without comments, preamble or URL arguments."""
    body = tex.split(r"\begin{document}", 1)[-1]
    body = "\n".join(re.sub(r"(?<!\\)%.*$", "", l) for l in body.splitlines())
    body = re.sub(r"\\href\{[^}]*\}", r"\\href{}", body)
    return re.sub(r"\\url\{[^}]*\}", "", body)


def _lang_of(path: Path) -> str:
    return path.parent.name


def check_file(path: Path, profile: dict, report: Report) -> None:
    tex = path.read_text(encoding="utf-8")
    plain = _plain(tex)
    body = _body(tex)
    lang = _lang_of(path)
    rel = path.relative_to(BASE_DIR)

    ident = profile["identity"]
    for label, value in [("name", ident["name"]), ("email", ident["email"]), ("phone", ident["phone"])] + \
                        [("link", l) for l in ident["links"]]:
        if value not in plain:
            report.add(rel, "error", "identity", f"{label} '{value}' from profile.yaml is missing")

    if "PLACEHOLDER" in tex:
        report.add(rel, "error", "placeholder", "template PLACEHOLDER text left in file")

    allowed = {m["value"].strip().rstrip("%") for m in profile.get("metrics", []) if m["value"].strip().endswith("%")}
    for pct in sorted(set(PERCENT.findall(body))):
        if pct not in allowed:
            report.add(rel, "error", "unverified-metric",
                       f"'{pct}%' is not in profile.yaml metrics - verify it and add it there, or remove it")

    if lang == "en":
        strong = set(ES_STRONG.findall(body))
        if strong:
            report.add(rel, "error", "wrong-language", f"Spanish section/date words in EN CV: {sorted(strong)}")
        scrubbed = re.sub(r"Universidad del Valle de Guatemala|Bodegas de Licores|Díaz Castañeda", "", body)
        hits = ES_WORDS.findall(scrubbed)
        if len(hits) > 3:
            report.add(rel, "warning", "wrong-language", f"{len(hits)} Spanish-looking words in EN CV: {sorted(set(hits))[:8]}")
    elif lang == "es":
        strong = set(EN_STRONG.findall(body))
        if strong:
            report.add(rel, "error", "wrong-language", f"English section/date words in ES CV: {sorted(strong)}")

    for exp in profile.get("experience", []):
        key = exp.get("key")
        if not key or key not in plain:
            continue
        start = exp["start"]
        if lang == "es":
            start = " ".join(ES_MONTHS.get(w, w) for w in start.split())
        lines = plain.splitlines()
        idx = next(i for i, l in enumerate(lines) if key in l)
        if start not in "\n".join(lines[idx:idx + 3]):
            report.add(rel, "error", "date", f"'{key}' start date should be '{start}' (profile.yaml)")

    scrubbed_math = re.sub(r"\$[^$]*\$", "", body)
    scrubbed_math = re.sub(r"\\href\{\}", "", scrubbed_math)
    for n, line in enumerate(scrubbed_math.splitlines(), start=1):
        if re.search(r"(?<!\\)[&_#]", line):
            report.add(rel, "error", "unescaped", f"unescaped &, _ or # in body text: {line.strip()[:70]}")
            break

    opens = len(re.findall(r"(?<!\\)\{", body))
    closes = len(re.findall(r"(?<!\\)\}", body))
    if opens != closes:
        report.add(rel, "error", "braces", f"unbalanced braces ({opens} '{{' vs {closes} '}}')")
    for env in set(re.findall(r"\\begin\{(\w+)\}", tex)):
        if len(re.findall(rf"\\begin\{{{env}\}}", tex)) != len(re.findall(rf"\\end\{{{env}\}}", tex)):
            report.add(rel, "error", "environment", f"unbalanced \\begin/\\end for '{env}'")
    if re.search(r"\\item\s*(\\\\)?\s*(\n\s*\\(item|end)|$)", body):
        report.add(rel, "error", "empty-item", "empty \\item")

    profile_skills = set(profile.get("skills", []))
    extra = [t for t in terms_in(plain) if t not in profile_skills]
    if extra:
        report.add(rel, "warning", "unverified-skill",
                   f"technologies in CV that are not in profile.yaml skills: {extra}")

    pdf = path.with_suffix(".pdf")
    if not pdf.exists():
        report.add(rel, "warning", "no-pdf", "no compiled PDF next to the .tex")
    else:
        if pdf.stat().st_mtime < path.stat().st_mtime:
            report.add(rel, "warning", "stale-pdf", "PDF is older than the .tex (recompile)")
        info = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
        m = re.search(r"Pages:\s+(\d+)", info)
        if m and int(m.group(1)) != 1:
            report.add(rel, "error", "pages", f"PDF has {m.group(1)} pages (must be exactly 1)")


def _signature(path: Path) -> dict:
    body = _body(path.read_text(encoding="utf-8"))
    return {
        "sections": len(re.findall(r"\\resumesection", body)),
        "items": len(re.findall(r"\\item\b", body)),
        "projects": len(re.findall(r"\\textbar\\ \\textit", body)),
        "numbers": Counter(t for t in NUMBER_TOKEN.findall(body) if len(t.replace("\\", "")) > 1),
    }


def check_parity(track_dir: Path, report: Report) -> None:
    en = sorted((track_dir / "en").glob("*.tex"))
    es = sorted((track_dir / "es").glob("*.tex"))
    rel = track_dir.relative_to(BASE_DIR)
    if not en or not es:
        report.add(rel, "error", "parity", "track is missing its en/ or es/ CV")
        return
    a, b = _signature(en[0]), _signature(es[0])
    for field in ("sections", "projects"):
        if a[field] != b[field]:
            report.add(rel, "error", "parity", f"{field}: en={a[field]} vs es={b[field]}")
    if a["items"] != b["items"]:  # a merged/split bullet is a legitimate translation choice
        report.add(rel, "warning", "parity", f"bullet count differs: en={a['items']} vs es={b['items']}")
    only_en = sorted((a["numbers"] - b["numbers"]).keys())
    only_es = sorted((b["numbers"] - a["numbers"]).keys())
    if only_en or only_es:
        report.add(rel, "warning", "parity", f"numbers differ between languages: only en {only_en}, only es {only_es}")


def run(path: str = None) -> dict:
    profile = load_profile()
    report = Report()
    if path:
        target = Path(path) if Path(path).is_absolute() else BASE_DIR / path
        files = [target]
    else:
        files = sorted(VERSIONS_DIR.glob("*/*/*.tex"))
        for track_dir in sorted(p for p in VERSIONS_DIR.iterdir() if p.is_dir()):
            check_parity(track_dir, report)
    for f in files:
        if f.exists():
            check_file(f, profile, report)
        else:
            report.add(f, "error", "missing", "file not found")
    errors = sum(i["level"] == "error" for i in report.issues)
    warnings = sum(i["level"] == "warning" for i in report.issues)
    return {"status": "success", "files_checked": len(files), "errors": errors,
            "warnings": warnings, "issues": report.issues}


def format_report(res: dict) -> str:
    lines = []
    for i in res["issues"]:
        mark = "ERROR" if i["level"] == "error" else "warn "
        lines.append(f"[{mark}] {i['file']}: ({i['code']}) {i['message']}")
    lines.append(f"\n{res['files_checked']} files checked: {res['errors']} errors, {res['warnings']} warnings")
    return "\n".join(lines)
