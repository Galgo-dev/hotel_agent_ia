"""Validation par le code de la fiche JSON extraite par le modèle : jamais de date inventée, champs manquants calculés."""
import re
from datetime import date

from src.devis import _norm, charger_grille

TYPES_CHAMBRE = ("simple", "double", "twin", "suite")
TYPES_REPAS = ("dejeuner", "diner", "pause_cafe")
TYPES_EVENEMENT = ("seminaire", "mariage", "voyage", "autre")


def _entier(valeur) -> int:
    """Entier positif ou 0."""
    try:
        return max(int(valeur), 0)
    except (TypeError, ValueError):
        return 0


def _date_iso(valeur) -> str | None:
    """Renvoie la date si elle est au format YYYY-MM-DD valide, sinon None (jamais de date inventée)."""
    if not isinstance(valeur, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valeur):
        return None
    try:
        return date.fromisoformat(valeur).isoformat()
    except ValueError:
        return None


def valider_fiche(brut: dict, demande: dict) -> dict:
    """Normalise la réponse du modèle en fiche conforme et calcule les champs manquants."""
    salles_grille = charger_grille()["salles"]
    manquants = []

    arrivee, depart = _date_iso(brut.get("arrivee")), _date_iso(brut.get("depart"))
    if arrivee and depart and depart <= arrivee:
        depart = None
    effectif = _entier(brut.get("effectif"))
    for nom, valeur in (("arrivee", arrivee), ("depart", depart), ("effectif", effectif)):
        if not valeur:
            manquants.append(nom)

    salles = []
    for s in brut.get("salles") or []:
        info = salles_grille.get(_norm(str(s.get("nom", ""))))
        if info:
            salles.append({"nom": info["nom"], "date": _date_iso(s.get("date"))})
    repas = []
    for r in brut.get("repas") or []:
        if r.get("type") in TYPES_REPAS and _entier(r.get("personnes")):
            repas.append({"type": r["type"], "date": _date_iso(r.get("date")),
                          "personnes": _entier(r["personnes"]), "quantite": _entier(r.get("quantite")) or 1})
    if any(s["date"] is None for s in salles):
        manquants.append("salles.date")
    if any(r["date"] is None for r in repas):
        manquants.append("repas.date")

    type_evenement = brut.get("type_evenement")
    chambres = brut.get("chambres") or {}
    return {
        "id": demande["id"], "client": str(brut.get("client") or ""),
        "type_evenement": type_evenement if type_evenement in TYPES_EVENEMENT else "autre",
        "arrivee": arrivee, "depart": depart, "hypothese": bool(brut.get("hypothese")) and bool(arrivee), "effectif": effectif,
        "chambres": {t: _entier(chambres.get(t)) for t in TYPES_CHAMBRE},
        "salles": salles, "repas": repas, "champs_manquants": manquants,
    }
