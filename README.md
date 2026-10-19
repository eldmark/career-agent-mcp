# CareerAgent MCP: Autonomous Job Search, ATS Auditing & LaTeX CV Engine

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![LaTeX: Native](https://img.shields.io/badge/LaTeX-Native%20(No%20Deps)-orange.svg)](https://www.latex-project.org/)

**CareerAgent MCP** is an open-source, fully self-hosted career automation framework. It combines a native **Model Context Protocol (MCP)** server, a local ATS keyword auditing engine, a multi-track **1-page strict LaTeX compiler**, and a persistent **browser automation protocol** for Claude Code and Chromium/Brave.

Zero vendor lock-in, zero credit limits, zero subscriptions, and 100% data privacy.

---

## 🌟 Key Architecture

```
                          ┌────────────────────────────────┐
                          │   Claude Code / LLM Clients    │
                          │   (Cursor, Windsurf, Claude)   │
                          └───────────────┬────────────────┘
                                          │ [MCP stdio JSON-RPC 2.0]
                                          ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             CareerAgent MCP Engine                               │
│                                                                                  │
│   • scrape_job(url)               -> Fast HTML parsing of job specs              │
│   • search_remote_jobs(query)     -> Free public endpoints (Remotive API)        │
│   • analyze_ats_fit(track, text)  -> Local keyword density & gap analysis        │
│   • compile_cv(tex_path)          -> pdflatex + 1-page verification via pdfinfo  │
│   • generate_outreach(co, role)   -> Recruiter pitch rendered from your profile  │
│   • lint_cv / tailor_cv           -> Fact-checked CVs, truthful per-job tailoring │
│   • log_application / followups   -> CSV+Excel tracker with follow-up drafts     │
└──────────────┬───────────────────────────────────────────────────┬───────────────┘
               │                                                   │
               ▼                                                   ▼
┌──────────────────────────────┐                   ┌──────────────────────────────┐
│   5 Specialized CV Tracks    │                   │ Browser Automation Protocol  │
│                              │                   │                              │
│ • 01_backend_engineer        │                   │ • Brave / Chromium CDP       │
│ • 02_fullstack_engineer      │                   │ • Persistent user profile    │
│ • 03_systems_cplusplus       │                   │ • Autofill Greenhouse/Lever  │
│ • 04_ai_software_engineer    │                   │ • Human-in-the-loop submit   │
│ • 05_data_analyst            │                   │                              │
└──────────────────────────────┘                   └──────────────────────────────┘
```

---

## 🚀 Quick Start

### 1. Installation & Setup
Clone the repository:
```bash
git clone https://github.com/eldmark/career-agent-mcp.git
cd career-agent-mcp
```

Copy the example profiles and configure your details:
```bash
cp profile.example.json profile.json   # browser autofill details
cp profile.example.yaml profile.yaml   # facts the linter and tailor enforce (gitignored)
# Edit both with your real, verifiable details
```

### 2. Batch Compile all CV Versions to PDF
Verify that all 10 specialized CV versions (5 tracks × EN/ES) compile to **exactly 1 page**:
```bash
./compile.sh
```

---

## 🛠️ CLI Usage

You can run `career_agent.py` directly from your terminal:

```bash
# 1. Audit ATS fit against a job URL:
./career_agent/career_agent.py match ai "https://apply.company.com/job/12345"

# 2. Search live remote engineering jobs (free public API):
./career_agent/career_agent.py search "AI Engineer" --limit 5

# 3. Clean and extract job requirements from any URL:
./career_agent/career_agent.py scrape "https://boards.greenhouse.io/..."

# 4. Compile and verify 1-page compliance:
./career_agent/career_agent.py compile versions/04_ai_software_engineer/en/resume_ai_engineer.tex

# 5. Generate a customized recruiter outreach message:
./career_agent/career_agent.py outreach "TechCorp" "Senior Backend Engineer" --lang en
```

---

## 🤖 MCP Server Setup

Connect **CareerAgent** directly to **Claude Code**, **Cursor**, **Windsurf**, or **Claude Desktop**:

### Configuration (`~/.claude.json` or MCP settings)
```json
{
  "mcpServers": {
    "career-agent": {
      "command": "python3",
      "args": [
        "/absolute/path/to/career-agent-mcp/career_agent/career_agent.py",
        "--mcp"
      ]
    }
  }
}
```

Once connected, your AI assistant can natively call:
* `scrape_job` - cleans a posting and reads its JSON-LD `JobPosting` (title, company); warns on JS-only pages
* `search_remote_jobs`
* `analyze_ats_fit` - splits missing keywords into `addable_keywords` (declared in `profile.yaml`) and `gap_keywords` (never claimed)
* `compile_cv` - two-pass `pdflatex`, cleans aux files, verifies 1 page
* `generate_outreach`
* `lint_cv`, `tailor_cv`
* `log_application`, `update_application`, `followups`, `auto_match_and_log`, `list_applications`

### Truthful by construction: `profile.yaml`, `lint`, `tailor`
`profile.yaml` is the single source of truth for what you can claim: identity, dates, allowed percentage metrics and real skills.

```bash
./career_agent/career_agent.py lint                 # identity, unverified metrics/skills, es/en parity,
                                                    # wrong-language text, LaTeX escapes, PDF pages/staleness
./career_agent/career_agent.py tailor "<job url>"   # best track + only truthful keywords -> applications/<job>/
./career_agent/career_agent.py tailor --text-file job.txt --company Acme --role "Backend Engineer"
./career_agent/career_agent.py update 1 "Entrevista"  # status changes; "Aplicado" schedules a follow-up in 7 days
./career_agent/career_agent.py followups            # overdue follow-ups with ready-to-send email drafts
python3 -m unittest discover -s tests               # test suite
```
The tracker's CSV is the source of truth (the xlsx is regenerated from it) and re-logging the same URL updates the row instead of duplicating it.

---

## 🌐 Browser Automation & ATS Autofill

To automate application searches across **Himalayas**, **Arc.dev**, **Real Work From Anywhere**, and **Remote Rocketship** while maintaining active logins:

1. Launch Brave or Chromium with a dedicated persistent profile:
   ```bash
   brave --user-data-dir="$HOME/.config/brave-jobhunt" --remote-debugging-port=9222 &
   ```
2. Log in manually once to your job portals.
3. Use Claude Code with the `@modelcontextprotocol/server-puppeteer` MCP server to navigate, fill out Greenhouse/Lever/Ashby fields, attach the compiled PDF, and leave the screen ready for your final human approval.

See [browser_agent/README.md](./browser_agent/README.md) for full instructions and selector mappings.

---

## 📂 Repository Structure

```
career-agent-mcp/
├── .gitignore                         <-- Ignores PDFs, logs, and private profile.json
├── README.md                          <-- Master documentation
├── profile.example.json               <-- Template browser-autofill profile
├── profile.example.yaml               <-- Template facts file used by lint and tailor
├── compile.sh                         <-- Multi-version 1-page batch compiler
├── ADAPTATION_PROMPT.md               <-- Master LLM adaptation prompt
├── career_agent/
│   ├── career_agent.py                <-- Dual-mode CLI & MCP stdio server
│   ├── tracker.py, lint.py, tailor.py <-- Tracker, CV linter, per-job tailoring
│   ├── keywords.py, cv_profile.py     <-- ATS glossary, profile loader
├── tests/                             <-- unittest suite
├── browser_agent/
│   ├── README.md                      <-- Browser automation protocol guide
│   └── autofill_config.example.json   <-- ATS selector mappings
├── templates/
│   └── cv_base.tex                    <-- Dependency-free LaTeX base template
└── versions/
    ├── 01_backend_engineer/           <-- APIs, Microservices, Databases, Security
    │   ├── en/resume_backend.tex
    │   └── es/cv_backend.tex
    ├── 02_fullstack_engineer/         <-- React, Next.js, Node.js, Cloud, Web3D
    │   ├── en/resume_fullstack.tex
    │   └── es/cv_fullstack.tex
    ├── 03_systems_performance_cplusplus/ <-- C++17, ARM, Low-Level, Concurrency
    │   ├── en/resume_systems.tex
    │   └── es/cv_systems.tex
    ├── 04_ai_software_engineer/       <-- LLMs, MCP, Agents, Function Calling
    │   ├── en/resume_ai_engineer.tex
    │   └── es/cv_ai_engineer.tex
    └── 05_data_analyst/               <-- Machine Learning, EDA, SQL CTEs, K-Means
        ├── en/resume_data_analyst.tex
        └── es/cv_data_analyst.tex
```

---

## 📄 License

MIT License. Designed and built for autonomous software engineering workflows.
