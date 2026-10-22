"""Disponibilités chambres et salles, en lecture seule sur les CSV de planning."""
import csv
from copy import deepcopy
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from src.devis import _norm, charger_grille, dates_sejour, saison_de

DOSSIER = Path(__file__).resolve().parent.parent / "ressource"
PLANNING_CHAMBRES = DOSSIER / "planning_chambres.csv"
PLANNING_SALLES = DOSSIER / "planning_salles.csv"
DECALAGE_MAX = 60


@lru_cache(maxsize=1)
def charger_planning() -> dict:
    """Lit les deux CSV (ouverts en lecture seule) : chambres occupées par nuit/type, salles prises par date."""
    chambres: dict[tuple[date, str], int] = {}
    with open(PLANNING_CHAMBRES, "r", encoding="utf-8", newline="") as f:
        for ligne in csv.DictReader(f):
            cle = (date.fromisoformat(ligne["date_nuit"]), _norm(ligne["type_chambre"]))
            chambres[cle] = chambres.get(cle, 0) + int(ligne["nombre_chambres"])
    with open(PLANNING_SALLES, "r", encoding="utf-8", newline="") as f:
        salles = {(date.fromisoformat(l["date"]), _norm(l["salle"])) for l in csv.DictReader(f)}
    jours = [d for d, _ in chambres]
    return {"chambres": chambres, "salles": salles, "debut": min(jours), "fin": max(jours)}


def consulter_disponibilites(fiche: dict) -> dict:
    """Vérifie chambres (nuit par nuit) et salles ; renvoie {'disponible': bool, 'conflits': [...]}."""
    arrivee, depart = dates_sejour(fiche)
    planning, grille, conflits = charger_planning(), charger_grille(), []

    nuits = [arrivee + timedelta(days=i) for i in range((depart - arrivee).days)]
    for nuit in nuits:
        if not planning["debut"] <= nuit <= planning["fin"]:
            conflits.append(f"{nuit} : hors de la période couverte par le planning")
            continue
        for type_ch, demande in fiche.get("chambres", {}).items():
            libres = grille["chambres"][_norm(type_ch)]["capacite"] - planning["chambres"].get((nuit, _norm(type_ch)), 0)
            if demande > libres:
                conflits.append(f"{nuit} : {demande} chambre(s) {type_ch} demandée(s), {libres} libre(s)")

    for salle in fiche.get("salles", []):
        jour = date.fromisoformat(salle["date"])
        if not planning["debut"] <= jour <= planning["fin"]:
            conflits.append(f"{salle['date']} : salle {salle['nom']} hors de la période du planning")
        elif (jour, _norm(salle["nom"])) in planning["salles"]:
            conflits.append(f"{salle['date']} : salle {salle['nom']} déjà occupée")
    return {"disponible": not conflits, "conflits": conflits}


def decaler_fiche(fiche: dict, jours: int) -> dict:
    """Copie de la fiche dont toutes les dates (séjour, salles, repas) sont décalées de `jours` jours."""
    def decale(iso: str) -> str:
        return (date.fromisoformat(iso) + timedelta(days=jours)).isoformat()
    copie = deepcopy(fiche)
    copie["arrivee"], copie["depart"] = decale(fiche["arrivee"]), decale(fiche["depart"])
    for element in copie.get("salles", []) + copie.get("repas", []):
        element["date"] = decale(element["date"])
    copie["decalage_jours"] = jours
    return copie


def _dans_la_grille(fiche: dict) -> bool:
    """Vrai si chaque nuit du séjour décalé tombe dans une saison tarifée."""
    arrivee, depart = dates_sejour(fiche)
    try:
        return all(saison_de(arrivee + timedelta(days=i)) for i in range((depart - arrivee).days))
    except ValueError:
        return False


def chercher_dates_alternatives(fiche: dict, n: int = 2) -> list[dict]:
    """Renvoie jusqu'à n fiches décalées, les plus proches possible, dont la disponibilité est vérifiée."""
    dates_sejour(fiche)  # lève DemandeIncomplete si dates ou effectif manquent
    decalages = sorted((k for k in range(-DECALAGE_MAX, DECALAGE_MAX + 1) if k), key=lambda k: (abs(k), k < 0))
    trouvees = []
    for jours in decalages:
        candidate = decaler_fiche(fiche, jours)
        if _dans_la_grille(candidate) and consulter_disponibilites(candidate)["disponible"]:
            trouvees.append(candidate)
            if len(trouvees) == n:
                break
    return trouvees
