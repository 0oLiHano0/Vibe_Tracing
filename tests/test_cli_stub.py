import pytest
from vibe_tracing.cli import main


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    # Argparse --version can write to stdout or stderr depending on python/argparse version
    output = captured.out + captured.err
    assert "vibe-tracing 0.1.0" in output


def test_cli_help(capsys):
    main([])
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert "Vibe Tracing" in output
    assert "analyze" in output
