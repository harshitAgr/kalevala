"""Secret redaction via google-re2 (linear-time, no ReDoS).

Pattern ordering matters: more-specific matchers fire first so later,
broader patterns don't misclassify. Each match is replaced by an inert
sentinel `«KR:type:len»`; later patterns cannot match the sentinel
because the guillemet delimiters and `KR:` prefix don't appear in any
pattern. Before return, sentinels are rewritten to `[REDACTED:type]`.
"""
from __future__ import annotations

import re2
from dataclasses import dataclass
import re as _re


# (name, compiled_re2_regex)
_PATTERNS = [
    ("anthropic",       re2.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}")),
    ("openai",          re2.compile(r"sk-(?:proj-|svcacct-|[A-Za-z0-9])[A-Za-z0-9_\-]{40,}")),
    ("aws_access_key",  re2.compile(r"(AKIA|ASIA)[0-9A-Z]{16}")),
    ("aws_secret",      re2.compile(r"(?i)aws_secret[^\n]{0,20}[A-Za-z0-9+/=]{40}")),
    ("github",          re2.compile(r"(ghp_|gho_|ghs_|ghu_|github_pat_)[A-Za-z0-9_]{20,}")),
    ("bearer",          re2.compile(r"(?i)authorization:\s*bearer\s+\S+")),
    ("private_key",     re2.compile(r"-----BEGIN [A-Z ]{0,30}PRIVATE KEY-----[\s\S]{0,1000}?-----END [A-Z ]{0,30}PRIVATE KEY-----")),
    ("jwt",             re2.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("google_api",      re2.compile(r"AIza[0-9A-Za-z\-_]{35}")),
    ("hf_token",        re2.compile(r"hf_[A-Za-z0-9]{20,}")),
    ("env_var",         re2.compile(
        r"(?i)\b(?:api[_\-]?key|secret[_\-]?key|access[_\-]?key|auth[_\-]?token|password)\b"
        r"\s*[=:]\s*[\"']?([A-Za-z0-9+/=_\-]{20,})(?:[\"']|\b)"
    )),
]


_SENTINEL_RE = _re.compile(r"«KR:([a-z_]+):\d+»")


@dataclass
class Scrubber:
    def scrub(self, text: str) -> tuple[str, dict[str, int]]:
        counts: dict[str, int] = {}
        out = text
        for name, pat in _PATTERNS:
            def _sub(m, _name=name):
                counts[_name] = counts.get(_name, 0) + 1
                return f"«KR:{_name}:{len(m.group(0))}»"
            out = pat.sub(_sub, out)
        # rewrite sentinels to display form, stripping lengths
        out = _SENTINEL_RE.sub(lambda m: f"[REDACTED:{m.group(1)}]", out)
        return out, counts
