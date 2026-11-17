"""Gera app/calibragem.py: em cada piso, todo estilo pilotado no ótimo chega à mesma força total (equivalência, spec 46 §9.3)."""
import json
import pprint
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import jogo  # noqa: E402

t = time.time()
tab = jogo.calibrar()
dest = Path(__file__).resolve().parents[1] / "app" / "calibragem.py"
dest.write_text('"""Gerado por scripts/calibrar.py (não editar à mão)."""\nNORMA = ' + pprint.pformat(tab, width=140) + "\n", encoding="utf-8")
print(json.dumps(tab, indent=1), f"\n{time.time() - t:.0f}s")
