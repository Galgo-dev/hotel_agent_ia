"""Tests du planning : disponibilités, dates alternatives réellement libres, fichiers jamais modifiés."""
import csv
import hashlib
from collections import defaultdict
from datetime import date, timedelta

import pytest

from src.devis import DemandeIncomplete
from src.planning import (PLANNING_CHAMBRES, PLANNING_SALLES, chercher_dates_alternatives,
                          consulter_disponibilites)

CAPACITE = {"simple": 30, "double": 35, "twin": 15, "suite": 5}


def fiche(**champs) -> dict:
    base = {"id": "demande_test", "arrivee": "2026-11-06", "depart": "2026-11-08", "effectif": 10,
            "chambres": {}, "salles": [], "repas": []}
    return {**base, **champs}


def fiche_incompatible() -> dict:
    """Séjour du 11 au 13 décembre : trop de doubles et Cèdre déjà prise le 12 (cas de la demande 08)."""
    return fiche(arrivee="2026-12-11", depart="2026-12-13", effectif=45,
                 chambres={"double": 12, "simple": 8}, salles=[{"nom": "Cèdre", "date": "2026-12-12"}],
                 repas=[{"type": "dejeuner", "date": "2026-12-12", "personnes": 45}])


def empreintes() -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in (PLANNING_CHAMBRES, PLANNING_SALLES)]


def test_demande_compatible_est_disponible():
    f = fiche(effectif=60, chambres={"double": 12, "suite": 2}, salles=[{"nom": "Cèdre", "date": "2026-11-07"}])
    assert consulter_disponibilites(f) == {"disponible": True, "conflits": []}


def test_chambres_insuffisantes_signalees():
    resultat = consulter_disponibilites(fiche_incompatible())
    assert not resultat["disponible"]
    assert any("double" in c for c in resultat["conflits"])
    assert not any("simple" in c for c in resultat["conflits"])  # 8 simples : il en reste assez


def test_salle_deja_occupee():
    f = fiche(salles=[{"nom": "Cèdre", "date": "2026-12-12"}])
    assert any("Cèdre" in c for c in consulter_disponibilites(f)["conflits"])


def test_nom_de_salle_sans_accent_reconnu():
    f = fiche(salles=[{"nom": "Erable", "date": "2026-12-10"}])  # Érable est prise ce jour-là
    assert not consulter_disponibilites(f)["disponible"]


def test_sejour_hors_planning_refuse():
    assert not consulter_disponibilites(fiche(arrivee="2027-02-10", depart="2027-02-12"))["disponible"]


def test_demande_incomplete_leve_une_erreur():
    with pytest.raises(DemandeIncomplete):
        consulter_disponibilites(fiche(depart=None))
    with pytest.raises(DemandeIncomplete):
        chercher_dates_alternatives(fiche(arrivee=None))


def test_alternatives_verifiees_dans_les_csv_bruts():
    """Contrôle indépendant : on relit les CSV sans passer par planning.py."""
    original = fiche_incompatible()
    alternatives = chercher_dates_alternatives(original, n=2)
    assert len(alternatives) == 2
    assert len({a["arrivee"] for a in alternatives}) == 2 and all(a["arrivee"] != original["arrivee"] for a in alternatives)

    with open(PLANNING_CHAMBRES, encoding="utf-8") as f:
        occupees = defaultdict(int)
        for l in csv.DictReader(f):
            occupees[(l["date_nuit"], l["type_chambre"])] += int(l["nombre_chambres"])
    with open(PLANNING_SALLES, encoding="utf-8") as f:
        salles_prises = {(l["date"], l["salle"]) for l in csv.DictReader(f)}

    for alt in alternatives:
        arrivee, depart = date.fromisoformat(alt["arrivee"]), date.fromisoformat(alt["depart"])
        for i in range((depart - arrivee).days):
            nuit = (arrivee + timedelta(days=i)).isoformat()
            for type_ch, demande in alt["chambres"].items():
                assert occupees[(nuit, type_ch)] + demande <= CAPACITE[type_ch]
        assert all((s["date"], s["nom"]) not in salles_prises for s in alt["salles"])


def test_planning_jamais_modifie():
    avant = empreintes()
    consulter_disponibilites(fiche_incompatible())
    chercher_dates_alternatives(fiche_incompatible())
    assert empreintes() == avant
