import json
from pathlib import Path

import pytest

import devtriage


def write_package(tmp_path, dependencies=None, scripts=None):
    data = {}
    if dependencies:
        data["dependencies"] = dependencies
    if scripts:
        data["scripts"] = scripts
    package_path = tmp_path / "package.json"
    package_path.write_text(json.dumps(data))
    return package_path


def test_detect_runner_defaults_to_pytest(tmp_path, monkeypatch):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    monkeypatch.chdir(tmp_path)
    assert devtriage.detect_test_runner() == "pytest"


@pytest.mark.parametrize(
    "deps,scripts,expected",
    [
        ({"jest": "^29.0.0"}, None, "jest"),
        (None, {"test": "jest"}, "jest"),
        ({"mocha": "^10.0.0"}, None, "mocha"),
        (None, {"ci": "mocha --reporter spec"}, "mocha"),
    ],
)
def test_detect_runner_with_js_configs(tmp_path, monkeypatch, deps, scripts, expected):
    write_package(tmp_path, dependencies=deps, scripts=scripts)
    monkeypatch.chdir(tmp_path)
    assert devtriage.detect_test_runner() == expected


def test_detect_runner_nose_ini(tmp_path, monkeypatch):
    (tmp_path / "setup.cfg").write_text("[nosetests]\nverbosity=2\n")
    monkeypatch.chdir(tmp_path)
    assert devtriage.detect_test_runner() == "nose"

