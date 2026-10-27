"""Separate bundled resources from per-user writable configuration and data."""
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    resources: Path
    home: Path

    @property
    def config(self):
        return self.home / '.env'

    @property
    def database(self):
        return self.home / 'data' / 'console.sqlite3'


def app_paths(desktop=False):
    resources = Path(__file__).resolve().parent.parent
    if os.environ.get('ETD_HOME'):
        home = Path(os.environ['ETD_HOME']).expanduser().resolve()
    elif desktop or getattr(sys, 'frozen', False):
        home = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'ASW-CR'
    else:
        home = resources
    return AppPaths(resources, home)
