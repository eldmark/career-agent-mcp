#!/usr/bin/env python3
"""
CareerAgent MCP Server & CLI Tool
Author: Marco Alejandro Díaz Castañeda
Description: Self-hosted, zero-dependency job search, ATS auditing, and CV automation engine.
             Operates both as a CLI tool and as a stdio Model Context Protocol (MCP) server.
"""

import sys
import os
import json
import csv
import re
import subprocess
import urllib.parse
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path
from html.parser import HTMLParser

sys.path.insert(0, str(Path(__file__).resolve().parent))

import tracker
import prompt_injection as pi
from cv_profile import load_profile
from keywords import terms_in

BASE_DIR = Path(__file__).resolve().parent.parent
VERSIONS_DIR = BASE_DIR / "versions"

TRACKS = [
    "01_backend_engineer",
    "02_fullstack_engineer",
    "03_systems_performance_cplusplus",
    "04_ai_software_engineer",
    "05_data_analyst",
]

TRACK_MAP = {
    "01": "01_backend_engineer",
    "backend": "01_backend_engineer",
    "02": "02_fullstack_engineer",
    "fullstack": "02_fullstack_engineer",
    "03": "03_systems_performance_cplusplus",
    "systems": "03_systems_performance_cplusplus",
    "c++": "03_systems_performance_cplusplus",
    "04": "04_ai_software_engineer",
    "ai": "04_ai_software_engineer",
    "05": "05_data_analyst",
    "data": "05_data_analyst"
}

def _profile() -> dict:
    try:
        return load_profile()
    except OSError:
        return {}


_PREFS = _profile().get("preferences", {})
DEFAULT_SALARY = _PREFS.get("salary", "")
DEFAULT_MODALITY = _PREFS.get("modality", "")
MAX_JOB_CHARS = 20000
MIN_JOB_WORDS = 80


class CleanHTMLTextExtractor(HTMLParser):
    """Collects visible text, skipping script/style/nav/etc. (nesting-aware)."""

    IGNORED = {'script', 'style', 'noscript', 'nav', 'footer', 'svg', 'head', 'template'}

    def __init__(self):
        super().__init__()
        self.text_blocks = []
        self.ignore_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.IGNORED:
            self.ignore_depth += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.IGNORED and self.ignore_depth > 0:
            self.ignore_depth -= 1

    def handle_data(self, data):
        if not self.ignore_depth:
            clean = data.strip()
            if clean:
                self.text_blocks.append(clean)

    def get_text(self):
        return "\n".join(self.text_blocks)


def html_to_text(html: str) -> str:
    parser = CleanHTMLTextExtractor()
    parser.feed(html)
    return parser.get_text()


def _find_job_posting(node):
    """Depth-first search for a schema.org JobPosting object in parsed JSON-LD."""
    if isinstance(node, list):
        for item in node:
            found = _find_job_posting(item)
            if found:
                return found
    elif isinstance(node, dict):
        kind = node.get("@type")
        if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
            return node
        for value in node.values():
            found = _find_job_posting(value)
            if found:
                return found
    return None


def extract_job_meta(html: str) -> dict:
    """Pulls title/company/description from JSON-LD JobPosting, falling back to og:/<title> tags."""
    meta = {"title": "", "company": "", "description": ""}
    for blob in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            posting = _find_job_posting(json.loads(blob))
        except ValueError:
            continue
        if posting:
            org = posting.get("hiringOrganization")
            meta["title"] = str(posting.get("title") or "")
            meta["company"] = str(org.get("name") if isinstance(org, dict) else org or "")
            meta["description"] = html_to_text(str(posting.get("description") or ""))
            break
    if not meta["title"]:
        og = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html, re.I)
        title = re.search(r'<title[^>]*>(.*?)</title>', html, re.S | re.I)
        raw = og.group(1) if og else (title.group(1) if title else "")
        meta["title"] = re.sub(r'\s+', ' ', raw).strip()
    if not meta["company"]:
        site = re.search(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', html, re.I)
        meta["company"] = site.group(1).strip() if site else ""
    return meta


def scrape_job(url: str) -> dict:
    """Scrapes a job posting from any URL (Greenhouse, Lever, LinkedIn, Workday, etc.)."""
    if not url.lower().startswith(("http://", "https://")):
        return {"status": "error", "message": f"Not an http(s) URL: {url}"}
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            content = resp.read().decode(charset, errors="ignore")
    except Exception as e:
        return {"status": "error", "message": f"Failed to scrape {url}: {e}"}

    meta = extract_job_meta(content)
    text = html_to_text(content)
    if len(meta["description"].split()) > len(text.split()):
        text = meta["description"]

    injection_res = pi.scan_text(text, raw_html=content)

    result = {
        "status": "success",
        "url": url,
        "title": meta["title"],
        "company": meta["company"],
        "character_count": len(text),
        "word_count": len(text.split()),
        "extracted_text": text[:MAX_JOB_CHARS],
        "prompt_injection": {
            "is_safe": injection_res["is_safe"],
            "risk_level": injection_res["risk_level"],
            "threat_count": injection_res["threat_count"],
            "threats": injection_res["threats"],
            "zero_width_count": injection_res["zero_width_count"],
        },
    }
    warnings = []
    if result["word_count"] < MIN_JOB_WORDS:
        warnings.append(
            "Very little text extracted: the page is probably rendered with JavaScript or behind a login. "
            "Paste the job description manually (match --text / tailor --text-file) instead of trusting this score."
        )
    if not injection_res["is_safe"]:
        warnings.append(
            f"SECURITY ALERT: {injection_res['risk_level']} prompt injection threat detected "
            f"({injection_res['threat_count']} patterns identified). Text has been sanitized."
        )
        result["sanitized_text"] = injection_res["sanitized_text"][:MAX_JOB_CHARS]
    if warnings:
        result["warning"] = " | ".join(warnings)
    return result


def check_prompt_injection(text: str = "", url: str = "") -> dict:
    """Scans untrusted text or a scraped URL for indirect prompt injection attacks."""
    if url:
        scraped = scrape_job(url)
        if scraped.get("status") != "success":
            return scraped
        text = scraped.get("extracted_text", "")
        pi_data = scraped.get("prompt_injection", {})
        return {
            "status": "success",
            "url": url,
            "is_safe": pi_data.get("is_safe", True),
            "risk_level": pi_data.get("risk_level", "CLEAN"),
            "threat_count": pi_data.get("threat_count", 0),
            "threats": pi_data.get("threats", []),
            "zero_width_count": pi_data.get("zero_width_count", 0),
            "report": pi.format_audit_report(pi_data),
            "sanitized_text": scraped.get("sanitized_text", text),
        }
    if not text:
        return {"status": "error", "message": "Provide either text or a valid URL to scan"}
    res = pi.scan_text(text)
    return {
        "status": "success",
        "url": "",
        "is_safe": res["is_safe"],
        "risk_level": res["risk_level"],
        "threat_count": res["threat_count"],
        "threats": res["threats"],
        "zero_width_count": res["zero_width_count"],
        "report": pi.format_audit_report(res),
        "sanitized_text": res["sanitized_text"],
    }


def search_remote_jobs(query: str, limit: int = 10) -> dict:
    """Queries free open remote job APIs (Remotive) with zero credentials."""
    encoded_query = urllib.parse.quote(query)
    url = f"https://remotive.com/api/remote-jobs?search={encoded_query}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "CareerAgent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return {"status": "error", "message": f"Search failed: {e}"}

    jobs = []
    for item in data.get("jobs", [])[:limit]:
        snippet = html_to_text(item.get("description", ""))[:400]
        jobs.append({
            "id": item.get("id"),
            "title": item.get("title"),
            "company": item.get("company_name"),
            "category": item.get("category"),
            "candidate_required_location": item.get("candidate_required_location"),
            "salary": item.get("salary") or "Not specified",
            "url": item.get("url"),
            "snippet": snippet + ("..." if len(snippet) == 400 else "")
        })
    return {"status": "success", "count": len(jobs), "jobs": jobs}


# -------------------------------------------------------------
# ATS MATCHING
# -------------------------------------------------------------

def tex_to_plain(tex: str) -> str:
    """Undo the LaTeX escapes that would hide keywords from the matcher."""
    for src, dst in ((r"\&", "&"), (r"\%", "%"), (r"\_", "_"), (r"\#", "#"), (r"\textbar", "|")):
        tex = tex.replace(src, dst)
    return tex


def score_cv_text(job_text: str, cv_tex: str) -> dict:
    """Compares glossary terms required by the job against those present in a CV's text."""
    required = terms_in(job_text)
    have = set(terms_in(tex_to_plain(cv_tex)))
    matching = [t for t in required if t in have]
    missing = [t for t in required if t not in have]
    real_skills = set(load_profile().get("skills", []))
    pct = (len(matching) / len(required) * 100) if required else 100.0
    return {
        "match_percentage": round(pct, 1),
        "total_job_tech_keywords": len(required),
        "matching_keywords": matching,
        "missing_keywords": missing,
        "addable_keywords": [t for t in missing if t in real_skills],
        "gap_keywords": [t for t in missing if t not in real_skills],
    }


def find_cv_tex(track: str, language: str) -> Path:
    resolved = TRACK_MAP.get(track.lower(), track)
    track_dir = VERSIONS_DIR / resolved / language
    if not track_dir.exists():
        raise FileNotFoundError(f"Track directory not found: {track_dir}")
    tex_files = sorted(track_dir.glob("*.tex"))
    if not tex_files:
        raise FileNotFoundError(f"No .tex file found in {track_dir}")
    return tex_files[0]


def analyze_ats_fit(track: str, job_text: str, language: str = "en") -> dict:
    """Audits ATS keywords between a Job Description and your local CV track."""
    try:
        tex = find_cv_tex(track, language)
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}
    result = score_cv_text(job_text, tex.read_text(encoding="utf-8"))
    pct = result["match_percentage"]
    injection_audit = pi.scan_text(job_text)
    if result["total_job_tech_keywords"] == 0:
        recommendation = "No known tech keywords detected in the text - check that the job text was extracted correctly"
    elif pct >= 85:
        recommendation = "High Fit (>85%) - Ready to apply"
    else:
        recommendation = "Add the 'addable_keywords' to Technical Skills; 'gap_keywords' are not in profile.yaml and must not be claimed"
    if not injection_audit["is_safe"]:
        recommendation = f"[SECURITY ALERT: {injection_audit['risk_level']} prompt injection threat in job description] " + recommendation
    return {
        "status": "success",
        "track_analyzed": TRACK_MAP.get(track.lower(), track),
        "language": language,
        "cv_file": str(tex),
        **result,
        "prompt_injection": {
            "is_safe": injection_audit["is_safe"],
            "risk_level": injection_audit["risk_level"],
            "threat_count": injection_audit["threat_count"],
        },
        "recommendation": recommendation,
    }


def match_best_track(job_text: str, language: str = "en") -> dict:
    """Audits a job description against all 5 CV tracks and returns the track with highest match."""
    results = {}
    for t in TRACKS:
        res = analyze_ats_fit(t, job_text, language)
        if res.get("status") == "success":
            results[t] = res["match_percentage"]
    if not results:
        return {"status": "error", "message": f"No CV tracks found for language '{language}'"}
    best_track = max(results, key=results.get)
    return {
        "status": "success",
        "best_track": best_track,
        "best_score": results[best_track],
        "all_scores": results,
        "details": analyze_ats_fit(best_track, job_text, language),
    }


# -------------------------------------------------------------
# CV COMPILATION
# -------------------------------------------------------------

def page_count(pdf_path: Path) -> int:
    proc = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True, text=True)
    m = re.search(r'Pages:\s+(\d+)', proc.stdout)
    return int(m.group(1)) if m else -1


def compile_cv(tex_path: str) -> dict:
    """Compiles a .tex file (two passes) and verifies strict 1-page compliance."""
    path = Path(tex_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        return {"status": "error", "message": f"File does not exist: {path}"}

    out_dir = path.parent
    cmd = ["pdflatex", "-interaction=batchmode", path.name]
    pdf_path = path.with_suffix(".pdf")
    try:
        pdf_path.unlink(missing_ok=True)
        for _ in range(2):
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(out_dir))
        if not pdf_path.exists():
            return {"status": "error", "message": "Compilation failed. PDF not generated.", "log": proc.stdout[-500:]}
        pages = page_count(pdf_path)
    except FileNotFoundError as e:
        return {"status": "error", "message": f"Missing tool: {e.filename}"}
    finally:
        for ext in (".aux", ".log", ".out", ".toc"):
            path.with_suffix(ext).unlink(missing_ok=True)

    return {
        "status": "success",
        "pdf_path": str(pdf_path),
        "pages": pages,
        "is_single_page": pages == 1,
        "message": "Perfect 1-page fit!" if pages == 1 else f"Warning: Document has {pages} pages. Adjust spacing."
    }


def resolve_track_pdf(track_str: str, language: str = "en"):
    """Finds or compiles the PDF for a given track name."""
    clean_track = track_str.split()[0].lower()
    resolved_track = TRACK_MAP.get(clean_track, clean_track)
    track_dir = VERSIONS_DIR / resolved_track / language
    if not track_dir.exists():
        return None
    pdfs = sorted(track_dir.glob("*.pdf"))
    if not pdfs:
        texs = sorted(track_dir.glob("*.tex"))
        if texs:
            compile_cv(str(texs[0]))
            pdfs = sorted(track_dir.glob("*.pdf"))
    return pdfs[0] if pdfs else None


# -------------------------------------------------------------
# MESSAGES
# -------------------------------------------------------------

def generate_outreach(company: str, role: str, language: str = "en") -> dict:
    """Recruiter pitch rendered from the `pitch` templates in profile.yaml ({company}, {role} placeholders)."""
    profile = _profile()
    template = (profile.get("pitch") or {}).get(language.lower()) or (profile.get("pitch") or {}).get("en")
    if not template:
        return {"status": "error", "message": "No `pitch` templates in profile.yaml (see profile.example.yaml)"}
    message = template.replace("\\n", "\n").format(company=company, role=role)
    return {"status": "success", "company": company, "role": role, "language": language, "pitch": message}


def generate_followup(company: str, role: str, applied_on: str = "", language: str = "en") -> str:
    """Short follow-up email to send after the application has gone quiet."""
    ident = _profile().get("identity", {})
    name = ident.get("name", "")
    site = f"https://{ident['links'][0]}" if ident.get("links") else ""
    if language.lower() == "es":
        when = f" el {applied_on}" if applied_on else " hace unos días"
        return (
            f"Asunto: Seguimiento - {role}\n\n"
            f"Hola Equipo de {company},\n\n"
            f"Apliqué a la vacante de {role}{when} y quería confirmar que mi postulación les llegó correctamente. "
            f"Sigo muy interesado en el puesto y con gusto comparto cualquier información adicional "
            f"o una demo de mis proyectos ({site}).\n\n"
            f"Gracias por su tiempo.\n{name}"
        )
    when = f" on {applied_on}" if applied_on else " recently"
    return (
        f"Subject: Following up - {role}\n\n"
        f"Hi {company} Team,\n\n"
        f"I applied for the {role} position{when} and wanted to make sure my application reached you. "
        f"I'm still very interested in the role and happy to share anything else that would help, "
        f"including a walkthrough of my projects ({site}).\n\n"
        f"Thank you for your time.\n{name}"
    )


# -------------------------------------------------------------
# TRACKER
# -------------------------------------------------------------

def _sync_xlsx(result: dict) -> dict:
    warning = tracker.export_xlsx(tracker.read_rows(), pdf_resolver=resolve_track_pdf)
    if warning:
        result["warning"] = warning
    return result


def log_application(
    company: str,
    role: str,
    expected_salary: str = DEFAULT_SALARY,
    modality: str = DEFAULT_MODALITY,
    url: str = "",
    track: str = "04_ai_software_engineer (EN)",
    ats_match: str = "N/A",
    status: str = "Por Aplicar",
    description: str = "",
    notes: str = "",
) -> dict:
    """Logs a job application (or updates the existing one with the same URL) in the tracker."""
    row, created = tracker.upsert({
        "Empresa": company,
        "Puesto / Título": role,
        "Salario Esperado": expected_salary,
        "Modalidad": modality,
        "URL de Vacante": url,
        "Track CV Usado": track,
        "ATS Match": ats_match,
        "Estado": status,
        "Descripción Resumida": description,
        "Notas / Siguiente Paso": notes,
    })
    lang = "es" if "(es)" in track.lower() else "en"
    pdf = resolve_track_pdf(track, lang) if track else None
    result = {
        "status": "success",
        "message": f"Application for '{role}' at '{company}' {'logged' if created else 'updated'} successfully.",
        "tracker_csv": str(tracker.CSV_PATH),
        "tracker_excel": str(tracker.XLSX_PATH),
        "logged_entry": {**row, "pdf_linked": str(pdf) if pdf else "None"},
    }
    return _sync_xlsx(result)


def update_application(app_id: int, status: str, notes: str = "", followup: str = "") -> dict:
    """Changes the status (and optionally notes / follow-up date) of an existing application."""
    result = tracker.update_status(int(app_id), status, notes, followup)
    return _sync_xlsx(result) if result["status"] == "success" else result


def followups(language: str = "") -> dict:
    """Lists applications whose follow-up date has arrived, with a ready-to-send email draft."""
    items = []
    for r in tracker.due_followups():
        lang = language or ("es" if "(es)" in r["Track CV Usado"].lower() else "en")
        items.append({
            "id": r["ID"],
            "company": r["Empresa"],
            "role": r["Puesto / Título"],
            "status": r["Estado"],
            "applied_on": r["Fecha"],
            "followup_due": r["Seguimiento"],
            "draft": generate_followup(r["Empresa"], r["Puesto / Título"], r["Fecha"], lang),
        })
    return {"status": "success", "count": len(items), "due": items}


def list_applications() -> dict:
    """Reads and returns all logged applications from the tracker."""
    try:
        apps = tracker.read_rows()
    except (OSError, csv.Error) as e:
        return {"status": "error", "message": f"Failed to read tracker: {e}"}
    return {"status": "success", "count": len(apps), "applications": apps}


def auto_match_and_log(
    url: str,
    company: str = "",
    role: str = "",
    expected_salary: str = DEFAULT_SALARY,
    modality: str = DEFAULT_MODALITY,
    status: str = "Por Aplicar",
    notes: str = "",
    language: str = "en",
) -> dict:
    """Scrapes a job posting, matches the optimal CV track, compiles the PDF, and logs it."""
    scraped = scrape_job(url)
    if scraped.get("status") != "success":
        return scraped
    job_text = scraped["extracted_text"]

    match_res = match_best_track(job_text, language)
    if match_res.get("status") != "success":
        return match_res
    best_track, best_score = match_res["best_track"], match_res["best_score"]

    host = urllib.parse.urlparse(url).hostname or "unknown"
    company = company or scraped.get("company") or host
    role = role or scraped.get("title") or "(revisar puesto)"
    lines = [l.strip() for l in job_text.splitlines() if len(l.strip()) > 3]
    desc_snippet = (" ".join(lines[:4])[:140] + "...") if lines else "Job posting extracted from URL."
    auto_notes = f"Auto-matched optimal track: {best_track} ({best_score}% ATS match)"
    if scraped.get("warning"):
        auto_notes += " | WARNING: poco texto extraído, verificar manualmente"

    res = log_application(
        company=company, role=role, expected_salary=expected_salary, modality=modality, url=url,
        track=f"{best_track} ({language.upper()})", ats_match=f"{best_score}%", status=status,
        description=desc_snippet, notes=notes or auto_notes,
    )
    res["matching_analysis"] = match_res
    if scraped.get("warning"):
        res["scrape_warning"] = scraped["warning"]
    return res


# -------------------------------------------------------------
# LINT / TAILOR (implemented in sibling modules)
# -------------------------------------------------------------

def lint_cv(path: str = "") -> dict:
    """Checks CV consistency (identity, metrics, es/en parity, language, escapes, page count)."""
    import lint
    return lint.run(path or None)


def tailor_cv(url: str = "", text: str = "", text_file: str = "", company: str = "", role: str = "",
              language: str = "en", track: str = "auto", log: bool = False) -> dict:
    """Builds a job-specific CV in applications/<company-role-date>/ from the best track."""
    import tailor
    return tailor.run(url=url, text=text, text_file=text_file, company=company, role=role,
                      language=language, track=track, log=log)


# -------------------------------------------------------------
# MCP SERVER PROTOCOL IMPLEMENTATION (JSON-RPC 2.0 stdio)
# -------------------------------------------------------------

S = {"type": "string"}
LANG = {"type": "string", "enum": ["en", "es"]}

TOOLS = {
    "scrape_job": (
        lambda a: scrape_job(a.get("url", "")),
        "Scrape clean text and requirements from any job posting URL (Greenhouse, Lever, LinkedIn, Workday, etc.). Returns title/company when the page exposes them.",
        {"url": {**S, "description": "The full HTTP/HTTPS URL of the job posting"}}, ["url"]),
    "search_remote_jobs": (
        lambda a: search_remote_jobs(a.get("query", ""), a.get("limit", 10)),
        "Search active remote software engineering jobs using open, free public APIs without credentials.",
        {"query": {**S, "description": "Search query e.g. 'AI Engineer', 'Python', 'Backend'"},
         "limit": {"type": "integer", "description": "Maximum number of jobs to return (default 10)"}}, ["query"]),
    "analyze_ats_fit": (
        lambda a: analyze_ats_fit(a.get("track", "ai"), a.get("job_text", ""), a.get("language", "en")),
        "Audit ATS keyword match and gap analysis between a job description and one of your CV tracks. Separates keywords that can be added truthfully (in profile.yaml) from real gaps.",
        {"track": {**S, "description": "Target track: 'backend', 'fullstack', 'systems', 'ai', 'data'"},
         "job_text": {**S, "description": "The raw job description text"},
         "language": {**LANG, "description": "CV language (default: en)"}}, ["track", "job_text"]),
    "compile_cv": (
        lambda a: compile_cv(a.get("tex_path", "")),
        "Compile any LaTeX CV file with pdflatex and verify strict 1-page compliance via pdfinfo.",
        {"tex_path": {**S, "description": "Relative or absolute path to the .tex file"}}, ["tex_path"]),
    "generate_outreach": (
        lambda a: generate_outreach(a.get("company", ""), a.get("role", ""), a.get("language", "en")),
        "Generate a concise recruiter/hiring manager outreach pitch tailored to your profile.",
        {"company": S, "role": S, "language": LANG}, ["company", "role"]),
    "log_application": (
        lambda a: log_application(
            company=a.get("company", ""), role=a.get("role", ""),
            expected_salary=a.get("expected_salary", DEFAULT_SALARY),
            modality=a.get("modality", DEFAULT_MODALITY), url=a.get("url", ""),
            track=a.get("track", "04_ai_software_engineer (EN)"), ats_match=a.get("ats_match", "N/A"),
            status=a.get("status", "Por Aplicar"), description=a.get("description", ""),
            notes=a.get("notes", "")),
        "Log a job application in the tracker (CSV + Excel). If the URL is already tracked, that row is updated instead of duplicated.",
        {"company": S, "role": S, "expected_salary": S, "modality": S, "url": S,
         "track": {**S, "description": "CV track used e.g. '04_ai_software_engineer (EN)'"},
         "ats_match": {**S, "description": "e.g. '95%'"},
         "status": {**S, "description": "'Por Aplicar', 'Aplicado (En Evaluación)', 'Entrevista', 'Rechazado', 'Oferta'"},
         "description": S, "notes": S}, ["company", "role"]),
    "update_application": (
        lambda a: update_application(a.get("id"), a.get("status", ""), a.get("notes", ""), a.get("followup", "")),
        "Change the status of an existing tracked application (by ID). Applied -> follow-up date is set 7 days out; closed states clear it.",
        {"id": {"type": "integer"}, "status": S, "notes": S,
         "followup": {**S, "description": "Optional follow-up date YYYY-MM-DD"}}, ["id", "status"]),
    "followups": (
        lambda a: followups(a.get("language", "")),
        "List tracked applications whose follow-up date has arrived, each with a ready-to-send follow-up email draft.",
        {"language": {**LANG, "description": "Force draft language (default: from the CV used)"}}, []),
    "auto_match_and_log": (
        lambda a: auto_match_and_log(
            url=a.get("url", ""), company=a.get("company", ""), role=a.get("role", ""),
            expected_salary=a.get("expected_salary", DEFAULT_SALARY),
            status=a.get("status", "Por Aplicar"), notes=a.get("notes", ""),
            language=a.get("language", "en")),
        "Scrape a job URL, score all 5 CV tracks, pick the best, and log it to the tracker.",
        {"url": S, "company": S, "role": S, "expected_salary": S, "status": S, "notes": S,
         "language": LANG}, ["url"]),
    "list_applications": (
        lambda a: list_applications(),
        "List all tracked job applications.", {}, []),
    "lint_cv": (
        lambda a: lint_cv(a.get("path", "")),
        "Lint the CVs: identity vs profile.yaml, unverified metrics, es/en parity, wrong-language text, LaTeX escapes, PDF page count/staleness.",
        {"path": {**S, "description": "Optional single .tex file; default lints every version"}}, []),
    "tailor_cv": (
        lambda a: tailor_cv(url=a.get("url", ""), text=a.get("text", ""), text_file=a.get("text_file", ""),
                            company=a.get("company", ""), role=a.get("role", ""),
                            language=a.get("language", "en"), track=a.get("track", "auto"),
                            log=bool(a.get("log", False))),
        "Create a job-specific CV in applications/<company-role-date>/: picks the best track, adds only truthful keywords from profile.yaml, recompiles, verifies 1 page, and writes a report.",
        {"url": S, "text": {**S, "description": "Job description text (alternative to url)"},
         "text_file": S, "company": S, "role": S, "language": LANG,
         "track": {**S, "description": "'auto' or backend/fullstack/systems/ai/data"},
         "log": {"type": "boolean", "description": "Also log it in the tracker as 'Por Aplicar'"}}, []),
    "check_prompt_injection": (
        lambda a: check_prompt_injection(text=a.get("text", ""), url=a.get("url", "")),
        "Scan untrusted job description text or a scraped URL for indirect prompt injections, jailbreaks, hidden instructions, zero-width evasion, or data exfiltration attempts.",
        {"text": {**S, "description": "Text to analyze for prompt injection"},
         "url": {**S, "description": "Optional URL to scrape and analyze (content + hidden HTML)"}}, []),
}


def _tools_schema() -> list:
    return [
        {"name": name, "description": desc,
         "inputSchema": {"type": "object", "properties": props, "required": required}}
        for name, (_fn, desc, props, required) in TOOLS.items()
    ]


def handle_request(req: dict):
    """Returns a JSON-RPC response dict, or None for notifications."""
    req_id = req.get("id")
    method = req.get("method")

    if method == "initialize":
        client_version = (req.get("params") or {}).get("protocolVersion") or "2024-11-05"
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": client_version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "career-agent-mcp", "version": "1.1.0"},
        }}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": _tools_schema()}}
    if method == "tools/call":
        params = req.get("params") or {}
        entry = TOOLS.get(params.get("name"))
        if not entry:
            payload, is_error = {"status": "error", "message": f"Unknown tool: {params.get('name')}"}, True
        else:
            try:
                payload = entry[0](params.get("arguments") or {})
                is_error = payload.get("status") == "error"
            except Exception as e:
                payload, is_error = {"status": "error", "message": f"{type(e).__name__}: {e}"}, True
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "content": [{"type": "text", "text": json.dumps(payload, indent=2, ensure_ascii=False)}],
            "isError": is_error,
        }}
    if req_id is not None:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return None


def run_mcp_server():
    """Implements the standard MCP stdio JSON-RPC 2.0 server loop."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        resp = handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


def _read_job_arg(text_or_url: str) -> str:
    if text_or_url.startswith(("http://", "https://")):
        scraped = scrape_job(text_or_url)
        if scraped.get("warning"):
            print(f"WARNING: {scraped['warning']}", file=sys.stderr)
        return scraped.get("extracted_text", "")
    return text_or_url


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--mcp":
        run_mcp_server()
        return

    import argparse
    parser = argparse.ArgumentParser(description="CareerAgent CLI & MCP Engine")
    sub = parser.add_subparsers(dest="command", help="Sub-commands")

    p = sub.add_parser("scrape", help="Scrape job text from a URL")
    p.add_argument("url")

    p = sub.add_parser("search", help="Search remote jobs")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=5)

    p = sub.add_parser("match", help="Audit ATS keyword match")
    p.add_argument("track", help="backend, fullstack, systems, ai, data")
    p.add_argument("text_or_url", help="Raw job text or HTTP URL")
    p.add_argument("--lang", default="en")

    p = sub.add_parser("compile", help="Compile .tex and verify 1 page")
    p.add_argument("path")

    p = sub.add_parser("outreach", help="Generate recruiter outreach message")
    p.add_argument("company")
    p.add_argument("role")
    p.add_argument("--lang", default="en")

    p = sub.add_parser("log", help="Log (or update by URL) a job application")
    p.add_argument("--company", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--salary", default=DEFAULT_SALARY)
    p.add_argument("--modality", default=DEFAULT_MODALITY)
    p.add_argument("--url", default="")
    p.add_argument("--track", default="04_ai_software_engineer (EN)")
    p.add_argument("--match", default="N/A")
    p.add_argument("--status", default="Por Aplicar")
    p.add_argument("--desc", default="")
    p.add_argument("--notes", default="")

    p = sub.add_parser("update", help="Change the status of a tracked application")
    p.add_argument("id", type=int)
    p.add_argument("status")
    p.add_argument("--notes", default="")
    p.add_argument("--followup", default="", help="YYYY-MM-DD")

    p = sub.add_parser("followups", help="Applications due for follow-up, with email drafts")
    p.add_argument("--lang", default="")

    p = sub.add_parser("match-and-log", help="Auto match optimal CV track and log it")
    p.add_argument("url")
    p.add_argument("--company", default="")
    p.add_argument("--role", default="")
    p.add_argument("--salary", default=DEFAULT_SALARY)
    p.add_argument("--status", default="Por Aplicar")
    p.add_argument("--notes", default="")
    p.add_argument("--lang", default="en")

    sub.add_parser("list-apps", help="List all logged applications")

    p = sub.add_parser("lint", help="Lint CVs against profile.yaml and for es/en parity")
    p.add_argument("path", nargs="?", default="")

    p = sub.add_parser("tailor", help="Create a job-specific CV in applications/")
    p.add_argument("url", nargs="?", default="")
    p.add_argument("--text-file", default="", help="Job description saved in a file ('-' for stdin)")
    p.add_argument("--company", default="")
    p.add_argument("--role", default="")
    p.add_argument("--lang", default="en")
    p.add_argument("--track", default="auto")
    p.add_argument("--log", action="store_true", help="Also add it to the tracker")

    p = sub.add_parser("scan-injection", help="Scan text or URL for indirect prompt injections")
    p.add_argument("target", nargs="?", default="", help="URL or job text to scan")
    p.add_argument("--file", default="", help="File containing text to scan")
    p.add_argument("--raw-html", default="", help="File containing raw HTML")

    args = parser.parse_args()
    dump = lambda obj: print(json.dumps(obj, indent=2, ensure_ascii=False))
    exit_code = 0

    if args.command == "scrape":
        dump(scrape_job(args.url))
    elif args.command == "search":
        dump(search_remote_jobs(args.query, args.limit))
    elif args.command == "match":
        dump(analyze_ats_fit(args.track, _read_job_arg(args.text_or_url), args.lang))
    elif args.command == "compile":
        dump(compile_cv(args.path))
    elif args.command == "outreach":
        print(generate_outreach(args.company, args.role, args.lang)["pitch"])
    elif args.command == "log":
        dump(log_application(
            company=args.company, role=args.role, expected_salary=args.salary, modality=args.modality,
            url=args.url, track=args.track, ats_match=args.match, status=args.status,
            description=args.desc, notes=args.notes))
    elif args.command == "update":
        dump(update_application(args.id, args.status, args.notes, args.followup))
    elif args.command == "followups":
        res = followups(args.lang)
        if not res["count"]:
            print("No hay seguimientos pendientes.")
        for item in res["due"]:
            print(f"--- #{item['id']} {item['company']} | {item['role']} (due {item['followup_due']}) ---")
            print(item["draft"], end="\n\n")
    elif args.command == "match-and-log":
        dump(auto_match_and_log(
            url=args.url, company=args.company, role=args.role, expected_salary=args.salary,
            status=args.status, notes=args.notes, language=args.lang))
    elif args.command == "list-apps":
        dump(list_applications())
    elif args.command == "lint":
        import lint
        res = lint_cv(args.path)
        print(lint.format_report(res))
        exit_code = 1 if res["errors"] else 0
    elif args.command == "tailor":
        res = tailor_cv(url=args.url, text_file=args.text_file, company=args.company, role=args.role,
                        language=args.lang, track=args.track, log=args.log)
        dump(res)
        exit_code = 1 if res.get("status") == "error" else 0
    elif args.command == "scan-injection":
        if args.file:
            text = Path(args.file).read_text(encoding="utf-8")
            dump(check_prompt_injection(text=text))
        elif args.target.startswith(("http://", "https://")):
            dump(check_prompt_injection(url=args.target))
        elif args.target:
            dump(check_prompt_injection(text=args.target))
        else:
            print("Provide a URL, text argument, or --file")
            exit_code = 1
    else:
        parser.print_help()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
