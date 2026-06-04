import sys
from pathlib import Path

# Ensure src/ is on the import path so `vibe_tracing` resolves from source,
# not from an installed (possibly stale) wheel.
_src = str(Path(__file__).resolve().parent / "src")
if _src not in sys.path:
    sys.path.insert(0, _src)
