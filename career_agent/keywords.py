"""Tech glossary used by the ATS matcher. canonical name -> aliases.

An alias that starts with "=" is matched case-sensitively (e.g. "=Go").
"""
import re

GLOSSARY = {
    # languages
    "python": [], "c++": ["c++14", "c++17", "cpp"], "c": ["=C"], "java": [],
    "typescript": [], "javascript": ["js", "ecmascript"], "go": ["golang", "=Go"],
    "rust": ["=Rust"], "php": [], "c#": ["csharp"], "kotlin": [], "swift": ["=Swift"],
    "ruby": ["ruby on rails"], "jetpack compose": ["compose"], "android": [], "react native": [], "stripe": [], "scala": [], "sql": [], "bash": ["shell scripting"],
    # frameworks
    "node.js": ["nodejs", "node"], "express.js": ["=Express", "expressjs"], "fastapi": [],
    "django": [], "flask": [], "spring boot": [], "laravel": [],
    "react": ["reactjs", "react.js"], "next.js": ["nextjs"], "vue": ["vue.js", "vuejs"],
    "angular": [], ".net": ["dotnet", "asp.net"], "three.js": ["threejs"],
    "tailwind": ["tailwind css"], "html": ["html5"], "css": ["css3"], "prisma": [],
    # data stores
    "postgresql": ["postgres"], "mysql": [], "mariadb": [], "sqlite": [],
    "mongodb": ["mongo"], "redis": [], "kafka": [], "rabbitmq": [],
    "elasticsearch": [], "graphql": [], "grpc": [],
    # architecture
    "rest": ["=REST", "restful", "rest api", "rest apis"], "api": ["apis"], "webhooks": ["webhook"],
    "microservices": ["microservice"], "event-driven": ["event driven"],
    "etl": [], "streaming": [], "concurrency": ["multithreading", "multi-threading"],
    # infra
    "docker": [], "kubernetes": ["k8s"], "terraform": [], "aws": ["amazon web services"],
    "gcp": ["google cloud"], "azure": [], "linux": [], "git": [],
    "ci/cd": ["cicd", "continuous integration"], "github actions": [], "jenkins": [],
    "nginx": [], "cloudflare": [], "grafana": [], "prometheus": [],
    # ai / ml
    "mcp": ["model context protocol"], "llm": ["llms", "large language model", "large language models"],
    "openai": [], "anthropic": ["claude"], "langchain": [], "langgraph": [],
    "rag": ["retrieval augmented generation", "retrieval-augmented generation"],
    "embeddings": ["embedding"], "vector": ["vector database", "vector search"],
    "bm25": [], "whisper": [], "function calling": ["tool calling"], "tool use": [],
    "agents": ["ai agents"], "agentic": [], "prompt engineering": ["prompt optimization"],
    "json schema": [], "machine learning": ["ml"], "deep learning": [],
    "pytorch": [], "tensorflow": [], "scikit-learn": ["sklearn", "scikit learn"],
    "pandas": [], "numpy": [], "random forest": [], "k-means": ["kmeans"],
    "eda": ["exploratory data analysis"], "cross-validation": ["cross validation"],
    "nlp": ["natural language processing"], "spark": ["pyspark"], "airflow": [],
    "dbt": [], "tableau": [], "power bi": ["powerbi"], "excel": [], "metabase": [],
    # security / testing
    "owasp": [], "security": ["cybersecurity"], "jwt": [], "oauth": ["oauth2"],
    "rbac": [], "jest": [], "vitest": [], "pytest": [], "playwright": [],
    "testing": ["unit testing", "tdd"],
    # systems
    "arm": ["=ARM", "arm cortex", "armv7"], "dma": [], "profiling": [], "assembly": [], "cmake": [], "gdb": [],
    "valgrind": [], "embedded": [], "sockets": ["tcp"],
    # process
    "agile": ["scrum"],
}

_BOUND_L = r"(?<![\w+#.])"
_BOUND_R = r"(?![\w+#])"


def _alias_pattern(alias: str):
    case_sensitive = alias.startswith("=")
    term = alias[1:] if case_sensitive else alias
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(_BOUND_L + re.escape(term) + _BOUND_R, flags)


# Canonical names that are ordinary English words or too short: only their aliases count.
NO_CANONICAL = {"c", "go", "rest", "express.js", "arm", "swift", "rust", "compose"}

_PATTERNS = {
    canon: ([] if canon in NO_CANONICAL else [_alias_pattern(canon)])
    + [_alias_pattern(a) for a in aliases]
    for canon, aliases in GLOSSARY.items()
}


def terms_in(text: str) -> list:
    """Canonical glossary terms found in text (original-case text expected)."""
    return [c for c, pats in _PATTERNS.items() if any(p.search(text) for p in pats)]
