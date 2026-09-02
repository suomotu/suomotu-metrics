"""CLI behavior: exit codes, defaults, the report path without a token."""

import sqlite3

from test_metrics import seed_scenario

from suomotu_metrics import db
from suomotu_metrics.__main__ import main


def seeded_db(tmp_path):
    path = tmp_path / "metrics.db"
    con = db.connect(path)
    seed_scenario(con)
    con.commit()
    con.close()
    return path


def test_report_runs_without_a_token(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    db_path = seeded_db(tmp_path)
    code = main(
        ["report", "acme/rocket", "--db", str(db_path), "--out", str(tmp_path / "out")]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "report:" in out
    assert (tmp_path / "out" / "acme-rocket").exists()


def test_collect_without_token_exits_2(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert main(["collect", "acme/rocket"]) == 2
    assert "GITHUB_TOKEN" in capsys.readouterr().err


def test_bad_repo_argument_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    code = main(["report", "not-a-repo", "--db", str(tmp_path / "x.db")])
    assert code == 2
    assert "owner/repo" in capsys.readouterr().err


def test_report_for_uncollected_repo_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    code = main(["report", "acme/unknown", "--db", str(tmp_path / "x.db")])
    assert code == 2
    assert "run collect first" in capsys.readouterr().err


def test_default_subcommand_is_run(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    # With no token, the injected default "run" hits the token check first.
    assert main(["acme/rocket"]) == 2


def test_default_subcommand_with_leading_flag(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    # A flag before the repo still gets the default subcommand injected:
    # reaching the token check (exit 2) proves argparse accepted the line.
    assert main(["--weeks", "4", "acme/rocket"]) == 2
    assert "GITHUB_TOKEN" in capsys.readouterr().err


def test_unwritable_db_path_gives_one_line_diagnostic(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    code = main(["report", "acme/rocket", "--db", "/proc/nope/metrics.db"])
    assert code == 1
    err = capsys.readouterr().err
    assert "cannot open database" in err and "--db" in err
