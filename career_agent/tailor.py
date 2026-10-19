"""tailor: build a job-specific CV from the best track, adding only keywords you really have."""
import re
import sys
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
APPLICATIONS_DIR = BASE_DIR / "applications"

ACRONYMS = {"mcp", "llm", "rag", "etl", "jwt", "rbac", "sql", "nlp", "dma", "eda", "owasp",
            "html", "css", "aws", "gcp", "api", "bm25", "arm", "ci/cd", "php"}
DISPLAY = {
    "github actions": "GitHub Actions", "openai": "OpenAI", "fastapi": "FastAPI",
    "postgresql": "PostgreSQL", "mysql": "MySQL", "mariadb": "MariaDB", "sqlite": "SQLite",
    "typescript": "TypeScript", "javascript": "JavaScript", "langchain": "LangChain",
    "langgraph": "LangGraph", "numpy": "NumPy", "json schema": "JSON Schema",
    "node.js": "Node.js", "next.js": "Next.js", "three.js": "Three.js", "express.js": "Express.js",
    "k-means": "K-Means", "scikit-learn": "Scikit-Learn", "c++": "C++", "mongodb": "MongoDB",
    "tailwind": "Tailwind CSS", "rest": "REST", "cmake": "CMake", "gdb": "GDB",
}
LABEL = {"en": "Also relevant", "es": "Adicional relevante"}


def display_name(term: str) -> str:
    if term in DISPLAY:
        return DISPLAY[term]
    if term in ACRONYMS:
        return term.upper()
    return " ".join(w[:1].upper() + w[1:] for w in term.split())


def slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].strip("-") or "job"


def _load_job(url, text, text_file, ca):
    meta = {"title": "", "company": "", "warning": ""}
    if url:
        scraped = ca.scrape_job(url)
        if scraped.get("status") != "success":
            return None, meta, scraped
        meta.update(title=scraped["title"], company=scraped["company"], warning=scraped.get("warning", ""))
        return scraped["extracted_text"], meta, None
    if text_file:
        src = sys.stdin.read() if text_file == "-" else Path(text_file).read_text(encoding="utf-8")
        return src, meta, None
    if text:
        return text, meta, None
    return None, meta, {"status": "error", "message": "Provide a job url, text, or text_file"}


def run(url="", text="", text_file="", company="", role="", language="en", track="auto", log=False) -> dict:
    import career_agent as ca
    import lint

    job_text, meta, error = _load_job(url, text, text_file, ca)
    if error:
        return error
    if len(job_text.split()) < ca.MIN_JOB_WORDS:
        return {"status": "error",
                "message": "Job text is too short to tailor against (JS-rendered page?). Save the description to a file and use --text-file.",
                "warning": meta["warning"]}

    company = company or meta["company"] or "company"
    role = role or meta["title"] or "role"

    if track == "auto":
        match = ca.match_best_track(job_text, language)
        if match.get("status") != "success":
            return match
        track_name, all_scores = match["best_track"], match["all_scores"]
    else:
        track_name, all_scores = ca.TRACK_MAP.get(track.lower(), track), {}

    try:
        src_tex = ca.find_cv_tex(track_name, language)
    except FileNotFoundError as e:
        return {"status": "error", "message": str(e)}
    source = src_tex.read_text(encoding="utf-8")
    before = ca.score_cv_text(job_text, source)

    slug = f"{slugify(company)}-{slugify(role)}-{date.today().isoformat()}"
    out_dir = APPLICATIONS_DIR / slug / language
    out_dir.mkdir(parents=True, exist_ok=True)
    (APPLICATIONS_DIR / slug / "job.txt").write_text(job_text, encoding="utf-8")
    prefix = "cv" if language == "es" else "resume"
    out_tex = out_dir / f"{prefix}_marco_diaz_{slugify(company, 20)}.tex"

    added = [display_name(t) for t in before["addable_keywords"]]
    tailored = source
    if added and r"\end{skilllist}" in source:
        line = f"    \\item \\textbf{{{LABEL[language]}:}} {', '.join(added)}\n"
        tailored = source.replace(r"\end{skilllist}", line + r"\end{skilllist}", 1)
    out_tex.write_text(tailored, encoding="utf-8")

    comp = ca.compile_cv(str(out_tex))
    note = ""
    if comp.get("status") == "success" and not comp["is_single_page"] and tailored != source:
        out_tex.write_text(source, encoding="utf-8")
        comp = ca.compile_cv(str(out_tex))
        added, tailored = [], source
        note = "Added keywords did not fit on one page, so the unmodified track CV was kept."

    after = ca.score_cv_text(job_text, tailored)
    lint_res = lint.run(str(out_tex))

    report = [
        f"# {role} @ {company}", "",
        f"- Source: {url or text_file or '(pasted text)'}",
        f"- Track: `{track_name}` ({language})",
        f"- ATS match: {before['match_percentage']}% -> {after['match_percentage']}%",
        f"- Pages: {comp.get('pages', '?')}",
        f"- Added to Technical Skills: {', '.join(added) or 'nothing'}",
    ]
    if note:
        report.append(f"- Note: {note}")
    if all_scores:
        report += ["", "## Track scores", *[f"- {t}: {s}%" for t, s in sorted(all_scores.items(), key=lambda x: -x[1])]]
    report += ["", "## Gaps (asked by the job, NOT in profile.yaml - do not claim)",
               *([f"- {g}" for g in after["gap_keywords"]] or ["- none"]),
               "", "## Lint", *([f"- [{i['level']}] {i['code']}: {i['message']}" for i in lint_res["issues"]] or ["- clean"])]
    (APPLICATIONS_DIR / slug / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")

    result = {
        "status": "success" if comp.get("status") == "success" else "error",
        "folder": str(APPLICATIONS_DIR / slug),
        "tex": str(out_tex),
        "pdf": comp.get("pdf_path", ""),
        "pages": comp.get("pages"),
        "track": track_name,
        "match_before": before["match_percentage"],
        "match_after": after["match_percentage"],
        "added_keywords": added,
        "gap_keywords": after["gap_keywords"],
        "lint_errors": lint_res["errors"],
        "lint_warnings": lint_res["warnings"],
        "note": note,
        "scrape_warning": meta["warning"],
    }
    if comp.get("status") != "success":
        result["message"] = comp.get("message", "compilation failed")
    if log and result["status"] == "success":
        logged = ca.log_application(
            company=company, role=role, url=url, track=f"{track_name} ({language.upper()})",
            ats_match=f"{after['match_percentage']}%", status="Por Aplicar",
            notes=f"CV adaptado: applications/{slug}/{language}/")
        result["logged"] = logged["message"]
    return result
