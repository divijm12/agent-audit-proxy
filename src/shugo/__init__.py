from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("shugo")  # single source of truth: pyproject.toml
except PackageNotFoundError:  # running from a source tree that isn't installed
    __version__ = "0+unknown"
