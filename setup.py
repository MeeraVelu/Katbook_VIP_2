# Metadata now lives in pyproject.toml (PEP 621). This shim keeps
# `pip install -e .` / legacy setuptools invocations working.
from setuptools import setup

setup()
