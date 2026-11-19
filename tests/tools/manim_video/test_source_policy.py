"""Tests for SourcePolicyValidator — static AST-based safety checker."""
from __future__ import annotations

import pytest

from learning_pipeline.tools.manim_video._contracts import ManimSourcePolicyError
from learning_pipeline.tools.manim_video._source_policy import SourcePolicyValidator


@pytest.fixture
def validator() -> SourcePolicyValidator:
    return SourcePolicyValidator()


_SAFE_SOURCE = """\
from manim import *

class SceneIntro(Scene):
    def construct(self):
        title = Text("Hello")
        self.play(Write(title))
        self.wait(2)
"""


def test_validates_clean_source(validator):
    validator.validate(_SAFE_SOURCE)


def test_rejects_os_import(validator):
    source = "import os\n" + _SAFE_SOURCE
    with pytest.raises(ManimSourcePolicyError, match="banned import 'os'"):
        validator.validate(source)


def test_rejects_sys_import(validator):
    source = "import sys\n" + _SAFE_SOURCE
    with pytest.raises(ManimSourcePolicyError, match="banned import 'sys'"):
        validator.validate(source)


def test_rejects_subprocess_import(validator):
    source = "import subprocess\n" + _SAFE_SOURCE
    with pytest.raises(ManimSourcePolicyError, match="banned import 'subprocess'"):
        validator.validate(source)


def test_rejects_from_os_import(validator):
    source = "from os import path\n" + _SAFE_SOURCE
    with pytest.raises(ManimSourcePolicyError, match="banned import"):
        validator.validate(source)


def test_rejects_from_socket_import(validator):
    source = "from socket import socket\n" + _SAFE_SOURCE
    with pytest.raises(ManimSourcePolicyError, match="banned import"):
        validator.validate(source)


def test_rejects_eval_call(validator):
    source = _SAFE_SOURCE + "\neval('1+1')\n"
    with pytest.raises(ManimSourcePolicyError, match="eval"):
        validator.validate(source)


def test_rejects_exec_call(validator):
    source = _SAFE_SOURCE + "\nexec('pass')\n"
    with pytest.raises(ManimSourcePolicyError, match="exec"):
        validator.validate(source)


def test_rejects_open_call(validator):
    source = _SAFE_SOURCE + "\nopen('/etc/passwd')\n"
    with pytest.raises(ManimSourcePolicyError, match="open"):
        validator.validate(source)


def test_rejects_dunder_import(validator):
    source = _SAFE_SOURCE + "\n__import__('os')\n"
    with pytest.raises(ManimSourcePolicyError, match="__import__"):
        validator.validate(source)


def test_collects_all_violations_before_raising(validator):
    source = "import os\nimport subprocess\neval('x')\n" + _SAFE_SOURCE
    try:
        validator.validate(source)
        pytest.fail("Expected ManimSourcePolicyError")
    except ManimSourcePolicyError as exc:
        msg = str(exc)
        assert "os" in msg
        assert "subprocess" in msg
        assert "eval" in msg


def test_rejects_syntax_error(validator):
    with pytest.raises(ManimSourcePolicyError, match="syntax error"):
        validator.validate("def broken(:\n    pass\n")


def test_rejects_requests_import(validator):
    source = "import requests\n" + _SAFE_SOURCE
    with pytest.raises(ManimSourcePolicyError, match="requests"):
        validator.validate(source)


def test_rejects_threading_import(validator):
    source = "import threading\n" + _SAFE_SOURCE
    with pytest.raises(ManimSourcePolicyError, match="threading"):
        validator.validate(source)
