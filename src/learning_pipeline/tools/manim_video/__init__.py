"""Canonical video.manim.render executor and supporting components.

Public entry points:
    RealManimVideoExecutor — real bounded-agentic executor
    ManimGenerationController — state machine used by the real executor and CLI

The FakeManimVideoExecutor lives in elearning_bundle/executor_fake_manim.py
and remains the default for local development and default tests.
"""
