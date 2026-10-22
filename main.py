"""Point d'entrée : l'agent traite toute la boîte de demandes.

Usage : python main.py [--sortie DOSSIER]   (par défaut, les fichiers sont écrits dans out/)
"""
import sys
from pathlib import Path

from src.agent import traiter_boite

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    dossier = Path(sys.argv[sys.argv.index("--sortie") + 1]) if "--sortie" in sys.argv else None
    traiter_boite(sortie=dossier)
