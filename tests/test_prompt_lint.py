import sys

import pytest

from provision import prompt_lint


def test_is_text_and_scan(tmp_path):
    path = tmp_path / "doc.txt"
    path.write_text("Ensure this has introduction.", encoding="utf-8")
    assert prompt_lint.is_text(path) is True
    issues = prompt_lint.scan_file(path, ["Introduction"])
    assert issues and "BANNED" in issues[0]


def test_prompt_lint_main_reports(tmp_path, monkeypatch, capsys):
    file = tmp_path / "doc.txt"
    file.write_text("look no further\nsection text", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["prog", "--root", str(tmp_path), "--sections", "intro"])
    with pytest.raises(SystemExit) as exc:
        prompt_lint.main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Issues found" in out


def test_prompt_lint_main_ok(tmp_path, monkeypatch, capsys):
    file = tmp_path / "doc.txt"
    file.write_text("Intro section", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["prog", "--root", str(tmp_path), "--sections", "Intro"])
    with pytest.raises(SystemExit) as exc:
        prompt_lint.main()
    assert exc.value.code == 0
    assert "No issues" in capsys.readouterr().out
