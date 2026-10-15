"""Absolute → relative path normalization."""
from kalevala.path_normalizer import normalize_paths, normalize_string


def test_normalize_project_paths():
    project_dir = "/home/user/projects/myapp"
    home = "/home/user"
    assert normalize_string(
        "edited /home/user/projects/myapp/src/handlers.py",
        home=home,
        project_dir=project_dir,
        project_name="myapp",
    ) == "edited myapp/src/handlers.py"


def test_normalize_home_paths_outside_project():
    assert normalize_string(
        "checked /home/user/scripts/foo.sh",
        home="/home/user",
        project_dir="/home/user/projects/myapp",
        project_name="myapp",
    ) == "checked ~/scripts/foo.sh"


def test_foreign_absolute_path_flagged_not_rewritten(capsys):
    out = normalize_string(
        "looked at /opt/vendor/tool.py",
        home="/home/user",
        project_dir="/home/user/projects/myapp",
        project_name="myapp",
    )
    assert out == "looked at /opt/vendor/tool.py"
    err = capsys.readouterr().err
    assert "/opt/vendor/tool.py" in err


def test_macos_users_path_flagged():
    # case-insensitive start char catches /Users/...
    out = normalize_string(
        "ran /Users/jane/code/x.py",
        home="/home/user",
        project_dir="/home/user/projects/myapp",
        project_name="myapp",
    )
    assert out == "ran /Users/jane/code/x.py"


def test_normalize_paths_walks_dict():
    data = {
        "summary": "edited /home/user/projects/myapp/x.py",
        "files_touched": [
            "/home/user/projects/myapp/x.py",
            "/home/user/notes.md",
        ],
        "count": 3,
    }
    out = normalize_paths(
        data,
        home="/home/user",
        project_dir="/home/user/projects/myapp",
        project_name="myapp",
    )
    assert out["summary"] == "edited myapp/x.py"
    assert out["files_touched"] == ["myapp/x.py", "~/notes.md"]
    assert out["count"] == 3


def test_project_rewrite_emits_no_stderr(capsys):
    """Rewriting a project path must not produce spurious 'unexpected path' warnings."""
    normalize_string(
        "edited /home/user/projects/myapp/src/handlers.py",
        home="/home/user",
        project_dir="/home/user/projects/myapp",
        project_name="myapp",
    )
    assert capsys.readouterr().err == ""


def test_home_rewrite_emits_no_stderr(capsys):
    normalize_string(
        "checked /home/user/notes.md",
        home="/home/user",
        project_dir="/home/user/projects/myapp",
        project_name="myapp",
    )
    assert capsys.readouterr().err == ""


def test_relative_paths_do_not_warn(capsys):
    kw = dict(home="/home/user", project_dir="/home/user/projects/myapp", project_name="myapp")
    for s in ("runs/dryrun_2026-10-13/report/index.html", "bench/A1.03.07-v1.0.1-run"):
        assert normalize_string(s, **kw) == s
    assert capsys.readouterr().err == ""


def test_absolute_paths_still_warn(capsys):
    kw = dict(home="/home/user", project_dir="/home/user/projects/myapp", project_name="myapp")
    normalize_string("see /opt/app/run.py and /etc/nginx/nginx.conf", **kw)
    err = capsys.readouterr().err
    assert "/opt/app/run.py" in err and "/etc/nginx/nginx.conf" in err
