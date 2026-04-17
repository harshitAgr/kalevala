"""Absolute → relative path normalization."""
from kalevala.path_normalizer import normalize_paths, normalize_string


def test_normalize_project_paths():
    project_dir = "/home/hars/projects/opet"
    home = "/home/hars"
    assert normalize_string(
        "edited /home/hars/projects/opet/src/val.py",
        home=home,
        project_dir=project_dir,
        project_name="opet",
    ) == "edited opet/src/val.py"


def test_normalize_home_paths_outside_project():
    assert normalize_string(
        "checked /home/hars/scripts/foo.sh",
        home="/home/hars",
        project_dir="/home/hars/projects/opet",
        project_name="opet",
    ) == "checked ~/scripts/foo.sh"


def test_foreign_absolute_path_flagged_not_rewritten(capsys):
    out = normalize_string(
        "looked at /opt/vendor/tool.py",
        home="/home/hars",
        project_dir="/home/hars/projects/opet",
        project_name="opet",
    )
    assert out == "looked at /opt/vendor/tool.py"
    err = capsys.readouterr().err
    assert "/opt/vendor/tool.py" in err


def test_macos_users_path_flagged():
    # case-insensitive start char catches /Users/...
    out = normalize_string(
        "ran /Users/jane/code/x.py",
        home="/home/hars",
        project_dir="/home/hars/projects/opet",
        project_name="opet",
    )
    assert out == "ran /Users/jane/code/x.py"


def test_normalize_paths_walks_dict():
    data = {
        "summary": "edited /home/hars/projects/opet/x.py",
        "files_touched": [
            "/home/hars/projects/opet/x.py",
            "/home/hars/notes.md",
        ],
        "count": 3,
    }
    out = normalize_paths(
        data,
        home="/home/hars",
        project_dir="/home/hars/projects/opet",
        project_name="opet",
    )
    assert out["summary"] == "edited opet/x.py"
    assert out["files_touched"] == ["opet/x.py", "~/notes.md"]
    assert out["count"] == 3


def test_project_rewrite_emits_no_stderr(capsys):
    """Rewriting a project path must not produce spurious 'unexpected path' warnings."""
    normalize_string(
        "edited /home/hars/projects/opet/src/val.py",
        home="/home/hars",
        project_dir="/home/hars/projects/opet",
        project_name="opet",
    )
    assert capsys.readouterr().err == ""


def test_home_rewrite_emits_no_stderr(capsys):
    normalize_string(
        "checked /home/hars/notes.md",
        home="/home/hars",
        project_dir="/home/hars/projects/opet",
        project_name="opet",
    )
    assert capsys.readouterr().err == ""
