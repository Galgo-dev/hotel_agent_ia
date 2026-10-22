"""Tests de l'extraction : validation par le code et appel au modèle simulé (aucun appel réseau)."""
from types import SimpleNamespace

import pytest

from src.extraction import ExtractionError, extraire_fiche, valider_fiche

DEMANDE = {"id": "demande_test", "expediteur": "Test <test@example.org>", "sujet": "Sujet", "corps": "Bonjour"}


def brut(**champs) -> dict:
    base = {"client": "Marie Test", "type_evenement": "mariage", "arrivee": "2026-11-06", "depart": "2026-11-08",
            "hypothese": False, "effectif": 60, "chambres": {"double": 12, "suite": 2},
            "salles": [{"nom": "Cèdre", "date": "2026-11-07"}],
            "repas": [{"type": "diner", "date": "2026-11-07", "personnes": 60, "quantite": 1}]}
    return {**base, **champs}


class FauxClient:
    """Imite client.messages.create et garde les arguments reçus."""
    def __init__(self, texte: str):
        self.appels, self.texte = [], texte
        self.messages = self

    def create(self, **kwargs):
        self.appels.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.texte)])


@pytest.fixture(autouse=True)
def modele(monkeypatch):
    monkeypatch.setenv("MODEL", "modele-de-test")


def test_fiche_complete_normalisee():
    fiche = valider_fiche(brut(salles=[{"nom": "Erable", "date": "2026-11-07"}]), DEMANDE)
    assert fiche["champs_manquants"] == []
    assert fiche["chambres"] == {"simple": 0, "double": 12, "twin": 0, "suite": 2}
    assert fiche["salles"] == [{"nom": "Érable", "date": "2026-11-07"}]
    assert fiche["id"] == "demande_test"


def test_sans_dates_champs_manquants():
    fiche = valider_fiche(brut(arrivee=None, depart=None), DEMANDE)
    assert fiche["champs_manquants"] == ["arrivee", "depart"]
    assert valider_fiche(brut(arrivee=None, depart=None, hypothese=True), DEMANDE)["hypothese"] is False


def test_depart_absent():
    assert valider_fiche(brut(depart=None), DEMANDE)["champs_manquants"] == ["depart"]


def test_date_mal_formee_jamais_inventee():
    fiche = valider_fiche(brut(arrivee="vendredi 6 novembre", depart="2026-11-31"), DEMANDE)
    assert fiche["arrivee"] is None and fiche["depart"] is None


def test_depart_avant_arrivee_refuse():
    fiche = valider_fiche(brut(arrivee="2026-11-08", depart="2026-11-06"), DEMANDE)
    assert fiche["depart"] is None and "depart" in fiche["champs_manquants"]


def test_date_de_salle_ou_de_repas_manquante():
    fiche = valider_fiche(brut(salles=[{"nom": "Lys", "date": None}],
                               repas=[{"type": "pause_cafe", "date": None, "personnes": 10, "quantite": 2}]), DEMANDE)
    assert fiche["champs_manquants"] == ["salles.date", "repas.date"]
    assert fiche["repas"][0]["quantite"] == 2


def test_prestations_inconnues_ignorees():
    fiche = valider_fiche(brut(salles=[{"nom": "Grand Hall", "date": "2026-11-07"}],
                               repas=[{"type": "buffet_vip", "date": "2026-11-07", "personnes": 5}]), DEMANDE)
    assert fiche["salles"] == [] and fiche["repas"] == []


def test_extraire_fiche_avec_reponse_en_bloc_markdown():
    client = FauxClient("```json\n" + __import__("json").dumps(brut()) + "\n```")
    fiche = extraire_fiche(DEMANDE, client=client)
    assert fiche["effectif"] == 60 and fiche["champs_manquants"] == []
    appel = client.appels[0]
    assert appel["model"] == "modele-de-test"
    assert "DONNÉE" in appel["system"] and "<courriel>" in appel["messages"][0]["content"]


def test_reponse_non_json_leve_une_erreur():
    with pytest.raises(ExtractionError):
        extraire_fiche(DEMANDE, client=FauxClient("Désolé, je ne peux pas."))
