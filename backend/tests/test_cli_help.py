"""``python -m hoops_gm --help`` must print usage and exit without side effects.

The one command a stranger runs to find out what this program does must not
bind a port, read settings (which means reading ``.env``, including Fantrax
credentials), or configure logging as a side effect of asking. This is
deliberately not "does --help print something" — that assertion would still
pass if ``--help`` also started the server. Instead it monkeypatches the three
things ``main()`` can do besides parsing arguments (``get_settings``,
``configure_logging``, ``uvicorn.run``) to raise if called, so any of them
being reached at all is a failure, not just an assertion mismatch.
"""

from __future__ import annotations

import sys

import pytest

from hoops_gm import __main__ as cli


def _forbid(name: str):
    def _raise(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"{name} must not be called by --help")

    return _raise


def test_help_exits_zero_and_prints_usage_without_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "get_settings", _forbid("get_settings"))
    monkeypatch.setattr(cli, "configure_logging", _forbid("configure_logging"))
    monkeypatch.setattr(cli.uvicorn, "run", _forbid("uvicorn.run"))
    monkeypatch.setattr(sys, "argv", ["python -m hoops_gm", "--help"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "usage" in captured.out.lower()
    assert captured.err == ""


def test_help_argument_parsing_actually_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard against a --help test that passes for the wrong reason.

    If ``main()`` never called ``parse_args`` at all (e.g. the parser was
    built but discarded), the test above would still pass: nothing raises,
    nothing prints, and the forbidden functions are still unreached only
    because the whole function returned early some other way. This confirms
    the parser is actually invoked, by checking a bogus flag is rejected with
    the normal argparse usage error (exit code 2) rather than silently
    ignored and falling through to the server startup path.
    """
    monkeypatch.setattr(cli, "get_settings", _forbid("get_settings"))
    monkeypatch.setattr(cli, "configure_logging", _forbid("configure_logging"))
    monkeypatch.setattr(cli.uvicorn, "run", _forbid("uvicorn.run"))
    monkeypatch.setattr(sys, "argv", ["python -m hoops_gm", "--not-a-real-flag"])

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 2
