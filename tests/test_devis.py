"""Tests du devis : les montants attendus sont calculés à la main depuis la grille tarifaire."""
import inspect
from datetime import date

import pytest

from src.devis import DemandeIncomplete, calculer_devis, devis_markdown, saison_de


def fiche(**champs) -> dict:
    base = {"id": "demande_test", "client": "Test", "arrivee": "2026-11-06", "depart": "2026-11-08",
            "effectif": 10, "chambres": {}, "salles": [], "repas": []}
    return {**base, **champs}


def fiche_mariage() -> dict:
    return fiche(effectif=60, chambres={"double": 12, "suite": 2},
                 salles=[{"nom": "Cèdre", "date": "2026-11-07"}],
                 repas=[{"type": "diner", "date": "2026-11-07", "personnes": 60}])


def fiche_deux_saisons() -> dict:
    return fiche(arrivee="2026-12-13", depart="2026-12-16", effectif=22,
                 chambres={"simple": 10, "double": 6},
                 salles=[{"nom": "Cèdre", "date": "2026-12-14"}],
                 repas=[{"type": "dejeuner", "date": "2026-12-14", "personnes": 22},
                        {"type": "dejeuner", "date": "2026-12-15", "personnes": 22},
                        {"type": "diner", "date": "2026-12-14", "personnes": 22}])


def test_mariage_total_calcule_a_la_main():
    # 12×120×2 + 2×210×2 + 650 + 60×68 + 28 logés×2 nuits×16
    assert calculer_devis(fiche_mariage())["total"] == 2880 + 840 + 650 + 4080 + 896 == 9346


def test_sejour_sur_deux_saisons():
    devis = calculer_devis(fiche_deux_saisons())
    # simples : 10×95×2 + 10×135 ; doubles : 6×120×2 + 6×165 ; salle ; repas ; 22 logés×3 nuits×16
    assert devis["total"] == 3250 + 2430 + 650 + 1408 + 1496 + 1056 == 10290
    montants = {l["libelle"]: l["montant"] for l in devis["lignes"]}
    assert montants["Chambre double – saison haute (6 ch. × 1 nuit(s))"] == 990


def test_limites_des_saisons():
    assert saison_de(date(2026, 12, 14)) == "basse"
    assert saison_de(date(2026, 12, 15)) == "haute"
    assert saison_de(date(2027, 1, 5)) == "haute"
    assert saison_de(date(2027, 1, 6)) == "intermediaire"


def test_pause_cafe_comptee_par_pause():
    f = fiche(repas=[{"type": "pause_cafe", "date": "2026-11-06", "personnes": 25, "quantite": 2}])
    assert calculer_devis(f)["total"] == 25 * 2 * 9


@pytest.mark.parametrize("champs", [{"depart": None}, {"arrivee": None}, {"effectif": 0}])
def test_demande_incomplete_leve_une_erreur(champs):
    with pytest.raises(DemandeIncomplete):
        calculer_devis(fiche(**champs))


def test_aucun_parametre_de_remise():
    assert list(inspect.signature(calculer_devis).parameters) == ["fiche"]


def test_markdown_contient_chaque_ligne_et_le_total():
    f = fiche_mariage()
    devis = calculer_devis(f)
    texte = devis_markdown(f, devis)
    assert all(l["libelle"] in texte for l in devis["lignes"])
    assert "9346.00 €" in texte
