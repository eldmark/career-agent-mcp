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
import re
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from html.parser import HTMLParser

BASE_DIR = Path(__file__).resolve().parent.parent
VERSIONS_DIR = BASE_DIR / "versions"

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

class CleanHTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text_blocks = []
        self.ignore_tag = False
        self.ignored_tags = {'script', 'style', 'noscript', 'nav', 'footer', 'svg', 'head'}

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.ignored_tags:
            self.ignore_tag = True

    def handle_endtag(self, tag):
        if tag.lower() in self.ignored_tags:
            self.ignore_tag = False

    def handle_data(self, data):
        if not self.ignore_tag:
            clean = data.strip()
            if clean:
                self.text_blocks.append(clean)

    def get_text(self):
        return "\n".join(self.text_blocks)


def scrape_job(url: str) -> dict:
    """Scrapes a job posting from any URL (Greenhouse, Lever, LinkedIn, Workday, etc.)."""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode('utf-8', errors='ignore')
            parser = CleanHTMLTextExtractor()
            parser.feed(content)
            extracted_text = parser.get_text()
            
            # Extract common job signals
            lines = [l for l in extracted_text.splitlines() if len(l) > 3]
            preview = lines[:40]
            
            return {
                "status": "success",
                "url": url,
                "character_count": len(extracted_text),
                "word_count": len(extracted_text.split()),
                "extracted_text": extracted_text[:12000] # Limit to relevant length
            }
    except Exception as e:
        return {"status": "error", "message": f"Failed to scrape {url}: {str(e)}"}


def search_remote_jobs(query: str, limit: int = 10) -> dict:
    """Queries free open remote job APIs (Remotive) with zero credentials."""
    encoded_query = urllib.parse.quote(query)
    url = f"https://remotive.com/api/remote-jobs?search={encoded_query}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "CareerAgent/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            jobs = []
            for item in data.get("jobs", [])[:limit]:
                # Clean HTML description
                parser = CleanHTMLTextExtractor()
                parser.feed(item.get("description", ""))
                clean_desc = parser.get_text()[:400] + "..."

                jobs.append({
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "company": item.get("company_name"),
                    "category": item.get("category"),
                    "candidate_required_location": item.get("candidate_required_location"),
                    "salary": item.get("salary") or "Not specified",
                    "url": item.get("url"),
                    "snippet": clean_desc
                })
            return {"status": "success", "count": len(jobs), "jobs": jobs}
    except Exception as e:
        return {"status": "error", "message": f"Search failed: {str(e)}"}


def analyze_ats_fit(track: str, job_text: str, language: str = "en") -> dict:
    """Audits ATS keywords between a Job Description and candidate's local CV track."""
    resolved_track = TRACK_MAP.get(track.lower(), track)
    track_dir = VERSIONS_DIR / resolved_track / language
    
    if not track_dir.exists():
        return {"status": "error", "message": f"Track directory not found: {track_dir}"}
    
    tex_files = list(track_dir.glob("*.tex"))
    if not tex_files:
        return {"status": "error", "message": f"No .tex file found in {track_dir}"}
    
    cv_content = tex_files[0].read_text(encoding="utf-8").lower()
    job_lower = job_text.lower()
    
    # Common tech keywords to audit
    KEYWORDS_POOL = [
        "python", "c++", "node.js", "typescript", "javascript", "fastapi", "react", "next.js",
        "docker", "postgresql", "sqlite", "redis", "linux", "mcp", "model context protocol",
        "rest", "api", "webhooks", "graphql", "langchain", "langgraph", "agentic", "agents",
        "llm", "openai", "anthropic", "whisper", "embeddings", "vector", "bm25", "rag",
        "json schema", "function calling", "tool use", "streaming", "owasp", "security",
        "jwt", "rbac", "ci/cd", "git", "github actions", "machine learning", "scikit-learn",
        "random forest", "k-means", "eda", "cross-validation", "profiling", "arm", "dma"
    ]
    
    required_keywords = [kw for kw in KEYWORDS_POOL if re.search(r'\b' + re.escape(kw) + r'\b', job_lower)]
    matching_keywords = [kw for kw in required_keywords if re.search(r'\b' + re.escape(kw) + r'\b', cv_content)]
    missing_keywords = [kw for kw in required_keywords if kw not in matching_keywords]
    
    match_percentage = (len(matching_keywords) / len(required_keywords) * 100) if required_keywords else 100.0
    
    return {
        "status": "success",
        "track_analyzed": resolved_track,
        "language": language,
        "cv_file": str(tex_files[0]),
        "match_percentage": round(match_percentage, 1),
        "total_job_tech_keywords": len(required_keywords),
        "matching_keywords": matching_keywords,
        "missing_keywords": missing_keywords,
        "recommendation": "High Fit (>85%) - Ready to apply" if match_percentage >= 85 else "Add missing keywords to Technical Skills or Summary before applying"
    }


def compile_cv(tex_path: str) -> dict:
    """Compiles a .tex file and verifies strict 1-page compliance."""
    path = Path(tex_path)
    if not path.is_absolute():
        path = BASE_DIR / path
        
    if not path.exists():
        return {"status": "error", "message": f"File does not exist: {path}"}
        
    output_dir = path.parent
    cmd = ["pdflatex", "-interaction=batchmode", f"-output-directory={output_dir}", str(path)]
    
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(output_dir))
        pdf_path = path.with_suffix(".pdf")
        
        if not pdf_path.exists():
            return {"status": "error", "message": "Compilation failed. PDF not generated.", "log": proc.stdout[-500:]}
            
        # Check page count
        info_proc = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True, text=True)
        page_match = re.search(r'Pages:\s+(\d+)', info_proc.stdout)
        pages = int(page_match.group(1)) if page_match else -1
        
        return {
            "status": "success",
            "pdf_path": str(pdf_path),
            "pages": pages,
            "is_single_page": pages == 1,
            "message": "Perfect 1-page fit!" if pages == 1 else f"Warning: Document has {pages} pages. Adjust spacing."
        }
    except Exception as e:
        return {"status": "error", "message": f"Execution error: {str(e)}"}


def generate_outreach(company: str, role: str, language: str = "en") -> dict:
    """Generates an assertive, builder-focused recruiter pitch."""
    if language.lower() == "es":
        message = (
            f"Hola Equipo de {company},\n\n"
            f"Vi su vacante de {role} y me llamó la atención su enfoque técnico. "
            f"Cuento con experiencia en producción optimizando microservicios de IA (reducción de un 30% en consumo de tokens), "
            f"arquitectando servidores bajo el estándar Model Context Protocol (MCP) con búsqueda híbrida (vectores + BM25 en SQLite) "
            f"y desarrollando backend transaccional de alta concurrencia.\n\n"
            f"Mi enfoque es 100% de constructor que entrega sistemas funcionando en producción. "
            f"Pueden consultar mi portafolio interactivo en {portfolio} y mi código en {github}.\n\n"
            f"Me encantaría conversar sobre su roadmap técnico. ¡Saludos!"
        )
    else:
        message = (
            f"Hi {company} Team,\n\n"
            f"I came across your {role} posting and was immediately drawn to your engineering focus. "
            f"I specialize in building production-grade AI systems: architecting custom Model Context Protocol (MCP) servers "
            f"with hybrid semantic search (dense vector embeddings + BM25 on SQLite), and launching AI gateway microservices "
            f"that reduced LLM token consumption by 30% in production through semantic prompt caching and strict JSON Schema validation.\n\n"
            f"I am a builder focused on shipping working software rather than prototypes. You can inspect my live interactive portfolio "
            f"at {portfolio} and code repositories at {github}.\n\n"
            f"I would love to learn more about your technical roadmap and how I can contribute from day one. Best regards!"
        )
    return {"status": "success", "company": company, "role": role, "language": language, "pitch": message}


def resolve_track_pdf(track_str: str, language: str = "en") -> Path:
    """Finds or compiles the PDF for a given track name."""
    clean_track = track_str.split()[0].lower()
    resolved_track = TRACK_MAP.get(clean_track, clean_track)
    track_dir = VERSIONS_DIR / resolved_track / language
    if track_dir.exists():
        pdfs = list(track_dir.glob("*.pdf"))
        if pdfs:
            return pdfs[0]
        texs = list(track_dir.glob("*.tex"))
        if texs:
            compile_cv(str(texs[0]))
            pdfs = list(track_dir.glob("*.pdf"))
            if pdfs:
                return pdfs[0]
    return None


def match_best_track(job_text: str, language: str = "en") -> dict:
    """Audits a job description against all 5 CV tracks and returns the track with highest match."""
    tracks = [
        "01_backend_engineer",
        "02_fullstack_engineer",
        "03_systems_performance_cplusplus",
        "04_ai_software_engineer",
        "05_data_analyst"
    ]
    results = {}
    best_track = None
    best_score = -1.0
    
    for t in tracks:
        res = analyze_ats_fit(t, job_text, language)
        if res.get("status") == "success":
            score = res.get("match_percentage", 0.0)
            results[t] = score
            if score > best_score:
                best_score = score
                best_track = t
                
    best_res = analyze_ats_fit(best_track, job_text, language) if best_track else {}
    return {
        "status": "success",
        "best_track": best_track,
        "best_score": best_score,
        "all_scores": results,
        "details": best_res
    }


def auto_match_and_log(
    url: str,
    company: str = "",
    role: str = "",
    expected_salary: str = "$45,000 - $65,000 USD/año",
    modality: str = "Remoto (LATAM)",
    status: str = "Por Aplicar",
    notes: str = "",
    language: str = "en"
) -> dict:
    """Scrapes a job posting, matches the optimal CV track, compiles the PDF, and logs to Excel."""
    scraped = scrape_job(url)
    if scraped.get("status") != "success":
        return scraped
    job_text = scraped.get("extracted_text", "")
    
    match_res = match_best_track(job_text, language)
    best_track = match_res.get("best_track", "04_ai_software_engineer")
    best_score = match_res.get("best_score", 0.0)
    score_str = f"{best_score}%"
    
    lines = [l.strip() for l in job_text.splitlines() if len(l.strip()) > 3]
    if not role and lines:
        role = lines[0][:40]
    if not company and len(lines) > 1:
        company = lines[1][:30]
        
    track_label = f"{best_track} ({language.upper()})"
    desc_snippet = " ".join(lines[2:6])[:140] + "..." if len(lines) > 2 else "Job posting extracted from URL."
    
    log_res = log_application(
        company=company,
        role=role,
        expected_salary=expected_salary,
        modality=modality,
        url=url,
        track=track_label,
        ats_match=score_str,
        status=status,
        description=desc_snippet,
        notes=notes or f"Auto-matched optimal track: {best_track} ({score_str} ATS match)"
    )
    
    log_res["matching_analysis"] = match_res
    return log_res


def log_application(
    company: str,
    role: str,
    expected_salary: str = "$45,000 - $65,000 USD/año",
    modality: str = "Remoto (LATAM)",
    url: str = "",
    track: str = "04_ai_software_engineer (EN)",
    ats_match: str = "N/A",
    status: str = "Por Aplicar",
    description: str = "",
    notes: str = ""
) -> dict:
    """Logs or updates a job application in job_applications_tracker.xlsx and .csv with hyperlinks."""
    from datetime import datetime
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    excel_path = BASE_DIR / "job_applications_tracker.xlsx"
    csv_path = BASE_DIR / "job_applications_tracker.csv"
    
    headers = [
        "ID", "Fecha", "Empresa", "Puesto / Título", "Salario Esperado", 
        "Modalidad", "URL de Vacante", "Track CV Usado", "ATS Match", 
        "Estado", "Descripción Resumida", "Notas / Siguiente Paso"
    ]
    
    current_id = 1
    # Excel logging
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        if excel_path.exists():
            wb = openpyxl.load_workbook(excel_path)
            ws = wb.active
        else:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Postulaciones"
            ws.views.sheetView[0].showGridLines = True
            ws.append(headers)
            ws.row_dimensions[1].height = 28
            header_fill = PatternFill(start_color="122644", end_color="122644", fill_type="solid")
            for col_idx in range(1, len(headers) + 1):
                c = ws.cell(row=1, column=col_idx)
                c.fill = header_fill
                c.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
                c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        current_id = ws.max_row
        row_data = [
            current_id, today_str, company, role, expected_salary,
            modality, url, track, ats_match, status, description, notes
        ]
        ws.append(row_data)
        curr_row = ws.max_row
        ws.row_dimensions[curr_row].height = 24
        
        thin_border = Border(
            left=Side(style="thin", color="D0D5DD"), right=Side(style="thin", color="D0D5DD"),
            top=Side(style="thin", color="D0D5DD"), bottom=Side(style="thin", color="D0D5DD")
        )
        
        lang_code = "es" if "(es)" in track.lower() else "en"
        pdf_file = resolve_track_pdf(track, lang_code)
        
        for col_idx in range(1, len(row_data) + 1):
            cell = ws.cell(row=curr_row, column=col_idx)
            cell.font = Font(name="Calibri", size=10)
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center", wrap_text=(col_idx in [11, 12]))
            
            if col_idx in [1, 2, 5, 6, 9]:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                
            # Hyperlink for URL
            if col_idx == 7 and url.startswith("http"):
                cell.hyperlink = url
                cell.font = Font(name="Calibri", size=10, color="004B91", underline="single")
                
            # Hyperlink for CV PDF
            if col_idx == 8 and pdf_file and pdf_file.exists():
                cell.hyperlink = f"file://{pdf_file.resolve()}"
                cell.font = Font(name="Calibri", size=10, color="004B91", underline="single")
                
            # Status styling
            if col_idx == 10:
                cell.alignment = Alignment(horizontal="center", vertical="center")
                cell.font = Font(name="Calibri", size=10, bold=True)
                if "aplicado" in status.lower():
                    cell.fill = PatternFill(start_color="E6F4EA", end_color="E6F4EA", fill_type="solid")
                    cell.font = Font(name="Calibri", size=10, bold=True, color="137333")
                elif "entrevista" in status.lower():
                    cell.fill = PatternFill(start_color="E8F0FE", end_color="E8F0FE", fill_type="solid")
                    cell.font = Font(name="Calibri", size=10, bold=True, color="1A73E8")

        wb.save(excel_path)
    except Exception:
        pass

    # CSV logging
    import csv
    file_exists = csv_path.exists()
    row_count = 1
    if file_exists:
        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                row_count = sum(1 for _ in f)
        except Exception:
            row_count = 1

    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(headers)
        writer.writerow([
            row_count, today_str, company, role, expected_salary,
            modality, url, track, ats_match, status, description, notes
        ])

    return {
        "status": "success",
        "message": f"Application for '{role}' at '{company}' logged successfully.",
        "tracker_excel": str(excel_path),
        "tracker_csv": str(csv_path),
        "logged_entry": {
            "id": current_id,
            "date": today_str,
            "company": company,
            "role": role,
            "expected_salary": expected_salary,
            "status": status,
            "track": track,
            "ats_match": ats_match,
            "pdf_linked": str(pdf_file) if pdf_file else "None"
        }
    }


def list_applications() -> dict:
    """Reads and returns all logged applications from the tracker."""
    import csv
    csv_path = BASE_DIR / "job_applications_tracker.csv"
    if not csv_path.exists():
        return {"status": "success", "count": 0, "applications": []}
    
    apps = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                apps.append(row)
        return {"status": "success", "count": len(apps), "applications": apps}
    except Exception as e:
        return {"status": "error", "message": f"Failed to read tracker: {str(e)}"}


# -------------------------------------------------------------
# MCP SERVER PROTOCOL IMPLEMENTATION (JSON-RPC 2.0 stdio)
# -------------------------------------------------------------

def run_mcp_server():
    """Implements the standard MCP stdio JSON-RPC 2.0 server loop."""
    
    TOOLS_SCHEMA = [
        {
            "name": "scrape_job",
            "description": "Scrape clean text and requirements from any job posting URL (Greenhouse, Lever, LinkedIn, Workday, etc.).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The full HTTP/HTTPS URL of the job posting"}
                },
                "required": ["url"]
            }
        },
        {
            "name": "search_remote_jobs",
            "description": "Search active remote software engineering jobs using open, free public APIs without credentials.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query e.g. 'AI Engineer', 'Python', 'Backend'"},
                    "limit": {"type": "integer", "description": "Maximum number of jobs to return (default 10)"}
                },
                "required": ["query"]
            }
        },
        {
            "name": "analyze_ats_fit",
            "description": "Audit ATS keyword match score and gap analysis between a job description and candidate's local CV tracks.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "track": {"type": "string", "description": "Target track: 'backend', 'fullstack', 'systems', 'ai', 'data'"},
                    "job_text": {"type": "string", "description": "The raw job description text"},
                    "language": {"type": "string", "enum": ["en", "es"], "description": "CV language: 'en' or 'es' (default: en)"}
                },
                "required": ["track", "job_text"]
            }
        },
        {
            "name": "compile_cv",
            "description": "Compile any LaTeX CV file with pdflatex and verify strict 1-page compliance via pdfinfo.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tex_path": {"type": "string", "description": "Relative or absolute path to the .tex file"}
                },
                "required": ["tex_path"]
            }
        },
        {
            "name": "generate_outreach",
            "description": "Generate a concise, high-impact recruiter/hiring manager outreach pitch tailored to candidate's background.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"},
                    "role": {"type": "string", "description": "Job title or role name"},
                    "language": {"type": "string", "enum": ["en", "es"], "description": "Language: 'en' or 'es'"}
                },
                "required": ["company", "role"]
            }
        },
        {
            "name": "log_application",
            "description": "Log or update a job application in the tracker spreadsheet (Excel & CSV) with status, salary, and notes.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"},
                    "role": {"type": "string", "description": "Job title"},
                    "expected_salary": {"type": "string", "description": "Target salary range e.g. '$45,000 - $65,000 USD/yr'"},
                    "modality": {"type": "string", "description": "e.g. 'Remoto (LATAM)' or 'Worldwide'"},
                    "url": {"type": "string", "description": "Job posting URL"},
                    "track": {"type": "string", "description": "CV track used e.g. '04_ai_software_engineer (EN)'"},
                    "ats_match": {"type": "string", "description": "ATS keyword match percentage e.g. '95%'"},
                    "status": {"type": "string", "description": "Status: 'Por Aplicar', 'Aplicado (En Evaluación)', 'Entrevista', 'Rechazado', 'Oferta'"},
                    "description": {"type": "string", "description": "Brief 1-2 sentence job summary"},
                    "notes": {"type": "string", "description": "Actionable next steps or interview notes"}
                },
                "required": ["company", "role"]
            }
        },
        {
            "name": "auto_match_and_log",
            "description": "Scrapes a job posting URL, evaluates all 5 CV tracks, selects the highest ATS match, compiles the PDF, and logs everything to Excel with clickable links.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The job posting URL"},
                    "company": {"type": "string", "description": "Company name (optional)"},
                    "role": {"type": "string", "description": "Job title (optional)"},
                    "expected_salary": {"type": "string", "description": "Target salary range e.g. '$45,000 - $65,000 USD/yr'"},
                    "status": {"type": "string", "description": "Status e.g. 'Por Aplicar' or 'Aplicado'"},
                    "language": {"type": "string", "enum": ["en", "es"], "description": "CV language: 'en' or 'es'"}
                },
                "required": ["url"]
            }
        },
        {
            "name": "list_applications",
            "description": "List all tracked job applications from the tracker spreadsheet.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        }
    ]

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue

        req_id = req.get("id")
        method = req.get("method")

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "career-agent-mcp",
                        "version": "1.0.0"
                    }
                }
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        elif method == "notifications/initialized":
            pass

        elif method == "ping":
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {}}) + "\n")
            sys.stdout.flush()

        elif method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": TOOLS_SCHEMA}
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {})

            result_content = {}
            if name == "scrape_job":
                result_content = scrape_job(args.get("url", ""))
            elif name == "search_remote_jobs":
                result_content = search_remote_jobs(args.get("query", ""), args.get("limit", 10))
            elif name == "analyze_ats_fit":
                result_content = analyze_ats_fit(args.get("track", "ai"), args.get("job_text", ""), args.get("language", "en"))
            elif name == "compile_cv":
                result_content = compile_cv(args.get("tex_path", ""))
            elif name == "generate_outreach":
                result_content = generate_outreach(args.get("company", ""), args.get("role", ""), args.get("language", "en"))
            elif name == "log_application":
                result_content = log_application(
                    company=args.get("company", ""),
                    role=args.get("role", ""),
                    expected_salary=args.get("expected_salary", "$45,000 - $65,000 USD/año"),
                    modality=args.get("modality", "Remoto (LATAM)"),
                    url=args.get("url", ""),
                    track=args.get("track", "04_ai_software_engineer (EN)"),
                    ats_match=args.get("ats_match", "N/A"),
                    status=args.get("status", "Por Aplicar"),
                    description=args.get("description", ""),
                    notes=args.get("notes", "")
                )
            elif name == "auto_match_and_log":
                result_content = auto_match_and_log(
                    url=args.get("url", ""),
                    company=args.get("company", ""),
                    role=args.get("role", ""),
                    expected_salary=args.get("expected_salary", "$45,000 - $65,000 USD/año"),
                    status=args.get("status", "Por Aplicar"),
                    notes=args.get("notes", ""),
                    language=args.get("language", "en")
                )
            elif name == "list_applications":
                result_content = list_applications()
            else:
                result_content = {"status": "error", "message": f"Unknown tool: {name}"}

            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result_content, indent=2, ensure_ascii=False)
                        }
                    ]
                }
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--mcp":
        run_mcp_server()
        return

    import argparse
    parser = argparse.ArgumentParser(description="CareerAgent CLI & MCP Engine")
    subparsers = parser.add_subparsers(dest="command", help="Sub-commands")

    p_scrape = subparsers.add_parser("scrape", help="Scrape job text from a URL")
    p_scrape.add_argument("url", help="Job posting URL")

    p_search = subparsers.add_parser("search", help="Search remote jobs")
    p_search.add_argument("query", help="Job title / skill query")
    p_search.add_argument("--limit", type=int, default=5, help="Number of jobs")

    p_ats = subparsers.add_parser("match", help="Audit ATS keyword match")
    p_ats.add_argument("track", help="Track: backend, fullstack, systems, ai, data")
    p_ats.add_argument("text_or_url", help="Raw job text or HTTP URL")
    p_ats.add_argument("--lang", default="en", help="Language: en or es")

    p_comp = subparsers.add_parser("compile", help="Compile .tex and verify 1 page")
    p_comp.add_argument("path", help="Path to .tex file")

    p_pitch = subparsers.add_parser("outreach", help="Generate recruiter outreach message")
    p_pitch.add_argument("company", help="Company name")
    p_pitch.add_argument("role", help="Job title")
    p_pitch.add_argument("--lang", default="en", help="Language: en or es")

    p_log = subparsers.add_parser("log", help="Log a job application into tracker spreadsheet")
    p_log.add_argument("--company", required=True, help="Company name")
    p_log.add_argument("--role", required=True, help="Job title")
    p_log.add_argument("--salary", default="$45,000 - $65,000 USD/año", help="Expected salary")
    p_log.add_argument("--modality", default="Remoto (LATAM)", help="Modality")
    p_log.add_argument("--url", default="", help="Job posting URL")
    p_log.add_argument("--track", default="04_ai_software_engineer (EN)", help="CV Track used")
    p_log.add_argument("--match", default="N/A", help="ATS match score")
    p_log.add_argument("--status", default="Por Aplicar", help="Status")
    p_log.add_argument("--desc", default="", help="Description")
    p_log.add_argument("--notes", default="", help="Next steps or notes")

    p_automatch = subparsers.add_parser("match-and-log", help="Auto match optimal CV track, compile PDF, and log to Excel")
    p_automatch.add_argument("url", help="Job posting URL")
    p_automatch.add_argument("--company", default="", help="Company name")
    p_automatch.add_argument("--role", default="", help="Job title")
    p_automatch.add_argument("--salary", default="$45,000 - $65,000 USD/año", help="Expected salary")
    p_automatch.add_argument("--status", default="Por Aplicar", help="Status")
    p_automatch.add_argument("--notes", default="", help="Notes")
    p_automatch.add_argument("--lang", default="en", help="Language: en or es")

    p_list = subparsers.add_parser("list-apps", help="List all logged applications from tracker")

    args = parser.parse_args()

    if args.command == "scrape":
        print(json.dumps(scrape_job(args.url), indent=2))
    elif args.command == "search":
        print(json.dumps(search_remote_jobs(args.query, args.limit), indent=2))
    elif args.command == "match":
        text = args.text_or_url
        if text.startswith("http://") or text.startswith("https://"):
            scraped = scrape_job(text)
            text = scraped.get("extracted_text", "")
        print(json.dumps(analyze_ats_fit(args.track, text, args.lang), indent=2))
    elif args.command == "compile":
        print(json.dumps(compile_cv(args.path), indent=2))
    elif args.command == "outreach":
        print(generate_outreach(args.company, args.role, args.lang).get("pitch"))
    elif args.command == "log":
        res = log_application(
            company=args.company, role=args.role, expected_salary=args.salary,
            modality=args.modality, url=args.url, track=args.track,
            ats_match=args.match, status=args.status, description=args.desc, notes=args.notes
        )
        print(json.dumps(res, indent=2))
    elif args.command == "match-and-log":
        res = auto_match_and_log(
            url=args.url, company=args.company, role=args.role,
            expected_salary=args.salary, status=args.status, notes=args.notes, language=args.lang
        )
        print(json.dumps(res, indent=2))
    elif args.command == "list-apps":
        print(json.dumps(list_applications(), indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
