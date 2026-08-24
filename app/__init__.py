"""Xingzhi Travel Companion backend.

The package is extended across the repository root and ``backend/app`` so the
team Trip Schema and the PBI-02-A location modules can coexist during local
integration.
"""

from pkgutil import extend_path
from pathlib import Path


__path__ = extend_path(__path__, __name__)
_team_app_path = Path(__file__).resolve().parent.parent / "backend" / "app"
if _team_app_path.is_dir():
    __path__.append(str(_team_app_path))
