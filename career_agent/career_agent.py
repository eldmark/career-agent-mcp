#!/usr/bin/env python3
"""
CareerAgent MCP Server & CLI Engine
Description: Self-hosted, zero-dependency job search, ATS auditing, and CV automation engine.
             Operates both as a CLI tool and as a stdio Model Context Protocol (MCP) server.
"""

import sys
import os
import json
import re
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path
from html.parser import HTMLParser

BASE_DIR = Path(__file__).resolve().parent.parent
VERSIONS_DIR = BASE_DIR / "versions"

def load_profile() -> dict:
    """Loads active profile.json if present, falling back to profile.example.json."""
    custom_profile = BASE_DIR / "profile.json"
    example_profile = BASE_DIR / "profile.example.json"
    
    target = custom_profile if custom_profile.exists() else example_profile
    if target.exists():
        try:
            return json.loads(target.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "personal": {
            "full_name": "Candidate",
            "website": "https://example.dev",
            "github": "https://github.com/example"
        }
    }

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
            
            return {
                "status": "success",
                "url": url,
                "character_count": len(extracted_text),
                "word_count": len(extracted_text.split()),
                "extracted_text": extracted_text[:12000]
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
    """Audits ATS keywords between a Job Description and the target CV track."""
    resolved_track = TRACK_MAP.get(track.lower(), track)
    track_dir = VERSIONS_DIR / resolved_track / language
    
    if not track_dir.exists():
        return {"status": "error", "message": f"Track directory not found: {track_dir}"}
    
    tex_files = list(track_dir.glob("*.tex"))
    if not tex_files:
        return {"status": "error", "message": f"No .tex file found in {track_dir}"}
    
    cv_content = tex_files[0].read_text(encoding="utf-8").lower()
    job_lower = job_text.lower()
    
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
    """Generates an assertive, builder-focused recruiter pitch parameterized by profile.json."""
    profile = load_profile()
    personal = profile.get("personal", {})
    portfolio = personal.get("website", "https://example.dev")
    github = personal.get("github", "https://github.com/example")

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


def run_mcp_server():
    """Implements standard MCP stdio JSON-RPC 2.0 server loop."""
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
            "description": "Audit ATS keyword match score and gap analysis between a job description and the local CV tracks.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "track": {"type": "string", "description": "Target track: 'backend', 'fullstack', 'systems', 'ai', 'data'"},
                    "job_text": {"type": "string", "description": "The raw job description text"},
                    "language": {"type": "string", "enum": ["en", "es"], "description": "CV language: 'en' or 'es'"}
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
            "description": "Generate a concise, high-impact recruiter outreach pitch tailored to candidate achievements.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "company": {"type": "string", "description": "Company name"},
                    "role": {"type": "string", "description": "Job title or role name"},
                    "language": {"type": "string", "enum": ["en", "es"], "description": "Language: 'en' or 'es'"}
                },
                "required": ["company", "role"]
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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
