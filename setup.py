from setuptools import setup, find_packages

setup(
    name="katbook_vip",
    version="2.1.0",
    description="Katbook Video Intelligence Platform pipeline",
    packages=find_packages(include=["katbook_vip", "katbook_vip.*"]),
    python_requires=">=3.9",
)
