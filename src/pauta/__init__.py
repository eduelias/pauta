"""Pauta: requests from whoever talks to the client to whoever runs the campaign."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("pauta")
except PackageNotFoundError:  # running from a bare source tree
    __version__ = "0+unknown"
