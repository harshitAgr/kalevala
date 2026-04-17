"""Normalize absolute paths in strings before persisting them.

Priority:
  1. $CLAUDE_PROJECT_DIR → <project_name>/
  2. $HOME → ~/
  3. Any remaining absolute POSIX-like path → kept as-is, flagged to stderr
"""
from __future__ import annotations

import re
import sys
from typing import Any

_FOREIGN_ABS = re.compile(r"/[A-Za-z_][A-Za-z0-9_/.\-]+\.[A-Za-z0-9]+")


def normalize_string(s: str, *, home: str, project_dir: str, project_name: str) -> str:
    # order matters: project first (more specific), then home
    if project_dir and not project_dir.endswith("/"):
        project_dir_s = project_dir + "/"
    else:
        project_dir_s = project_dir
    if home and not home.endswith("/"):
        home_s = home + "/"
    else:
        home_s = home

    out = s
    if project_dir_s:
        out = out.replace(project_dir_s, f"{project_name}/")
    if home_s:
        out = out.replace(home_s, "~/")

    for match in _FOREIGN_ABS.finditer(out):
        path = match.group(0)
        # skip anything we've already rewritten
        if path.startswith("~/") or path.startswith(f"{project_name}/"):
            continue
        print(f"[kalevala] unexpected absolute path retained: {path}", file=sys.stderr)
    return out


def normalize_paths(obj: Any, *, home: str, project_dir: str, project_name: str) -> Any:
    if isinstance(obj, str):
        return normalize_string(obj, home=home, project_dir=project_dir, project_name=project_name)
    if isinstance(obj, list):
        return [normalize_paths(x, home=home, project_dir=project_dir, project_name=project_name) for x in obj]
    if isinstance(obj, dict):
        return {k: normalize_paths(v, home=home, project_dir=project_dir, project_name=project_name) for k, v in obj.items()}
    return obj
