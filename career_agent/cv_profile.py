"""Loader for profile.yaml. Uses PyYAML when installed, else a tiny subset parser."""
import csv
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
# profile.yaml is personal and gitignored in public clones; fall back to the committed example.
PROFILE_PATH = _ROOT / "profile.yaml" if (_ROOT / "profile.yaml").exists() else _ROOT / "profile.example.yaml"


def _scalar(val: str):
    val = val.strip()
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        row = next(csv.reader([inner], skipinitialspace=True))
        return [_scalar(x) for x in row]
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        return val[1:-1]
    return val


def _strip_comment(line: str) -> str:
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] == " "):
            break
        out.append(ch)
    return "".join(out).rstrip()


_KEY_RE = re.compile(r"""^("[^"]*"|'[^']*'|[^'"\[\s][^:]*?):(?:\s+(.*))?$""")


def _parse_subset(text: str):
    lines = []
    for raw in text.splitlines():
        clean = _strip_comment(raw)
        if clean.strip():
            lines.append((len(clean) - len(clean.lstrip()), clean.strip()))

    def block(i, indent):
        if lines[i][1].startswith("- "):
            return seq(i, indent)
        return mapping(i, indent)

    def seq(i, indent):
        out = []
        while i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
            rest = lines[i][1][2:].strip()
            if _KEY_RE.match(rest) and not rest.startswith("["):
                lines[i] = (indent + 2, rest)
                item, i = mapping(i, indent + 2)
                out.append(item)
            else:
                out.append(_scalar(rest))
                i += 1
        return out, i

    def mapping(i, indent):
        out = {}
        while i < len(lines) and lines[i][0] == indent and not lines[i][1].startswith("- "):
            m = _KEY_RE.match(lines[i][1])
            if not m:
                raise ValueError(f"profile.yaml: cannot parse line {lines[i][1]!r}")
            key, val = _scalar(m.group(1)), m.group(2)
            i += 1
            if val is None or val == "":
                if i < len(lines) and lines[i][0] > indent:
                    out[key], i = block(i, lines[i][0])
                else:
                    out[key] = ""
            else:
                out[key] = _scalar(val)
        return out, i

    data, _ = block(0, lines[0][0])
    return data


def load_profile(path: Path = PROFILE_PATH) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        return _parse_subset(text)
