"""Point d'entrée : traite toute la boîte de demandes (python main.py)."""
import sys

from src.agent import traiter_boite

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    traiter_boite()
