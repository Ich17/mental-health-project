import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

import os

# Tests déterministes : profil fictif de contracts.py, même si des données réelles/simulées sont en local.
os.environ["DAILY_DATA"] = "mock"
