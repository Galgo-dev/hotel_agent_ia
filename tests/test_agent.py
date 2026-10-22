"""Tests de l'agent : extraction et rédaction simulées, sorties écrites dans un dossier temporaire."""
from types import SimpleNamespace

import pytest

from src.agent import traiter_boite, traiter_demande
from src.brouillons import _fr
from src.planning import consulter_disponibilites


def demande(id_: str) -> dict:
    return {"id": id_, "expediteur": "Client Test <client@example.org>", "sujet": "Demande de groupe", "corps": "..."}


def fiche(id_: str, **champs) -> dict:
    base = {"id": id_, "client": "Client Test", "type_evenement": "seminaire", "arrivee": "2026-11-06",
            "depart": "2026-11-08", "hypothese": False, "effectif": 60,
            "chambres": {"simple": 0, "double": 12, "twin": 0, "suite": 2},
            "salles": [{"nom": "Cèdre", "date": "2026-11-07"}],
            "repas": [{"type": "diner", "date": "2026-11-07", "personnes": 60, "quantite": 1}],
            "champs_manquants": []}
    return {**base, **champs}


def extraire_avec(*fiches):
    """Fausse extraction : renvoie la fiche portant l'id de la demande."""
    par_id = {f["id"]: f for f in fiches}
    return lambda d, client=None: par_id[d["id"]]


class FauxModele:
    """Imite client.messages.create en renvoyant un texte fixe."""
    def __init__(self, texte: str):
        self.texte, self.messages = texte, self

    def create(self, **kwargs):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.texte)])


@pytest.fixture(autouse=True)
def modele(monkeypatch):
    monkeypatch.setenv("MODEL", "modele-de-test")


def traiter(f, tmp_path, client=None):
    return traiter_demande(demande(f["id"]), client, extraire_avec(f), tmp_path)


def test_demande_sans_dates_aucun_devis(tmp_path):
    f = fiche("demande_04", arrivee=None, depart=None, champs_manquants=["arrivee", "depart"])
    resume = traiter(f, tmp_path)
    assert resume["type"] == "precisions" and resume["total"] is None
    assert list((tmp_path / "devis").glob("*")) == []
    assert (tmp_path / "brouillons" / "demande_04_precisions.md").exists()


def test_demande_sans_depart_aucun_devis(tmp_path):
    f = fiche("demande_09", depart=None, champs_manquants=["depart"])
    resume = traiter(f, tmp_path)
    assert resume["type"] == "precisions"
    assert not (tmp_path / "devis").exists() or list((tmp_path / "devis").glob("*")) == []
    assert "date de départ" in resume["fichier"].read_text(encoding="utf-8")


def test_demande_compatible_recoit_proposition_et_devis(tmp_path):
    resume = traiter(fiche("demande_01"), tmp_path)
    assert resume["type"] == "proposition" and resume["total"] == 9346
    brouillon = resume["fichier"].read_text(encoding="utf-8")
    assert "**Pièce jointe :** devis/demande_01.md" in brouillon
    assert "Service commercial – Le Grand Cèdre" in brouillon
    assert "9346.00 €" in (tmp_path / "devis" / "demande_01.md").read_text(encoding="utf-8")


def test_demande_incompatible_recoit_des_dates_reellement_libres(tmp_path):
    f = fiche("demande_08", arrivee="2026-12-11", depart="2026-12-13", effectif=45,
              chambres={"simple": 8, "double": 12, "twin": 0, "suite": 0},
              salles=[{"nom": "Cèdre", "date": "2026-12-12"}],
              repas=[{"type": "dejeuner", "date": "2026-12-12", "personnes": 45, "quantite": 1}])
    resume = traiter(f, tmp_path)
    assert resume["type"] == "alternatives" and len(resume["alternatives"]) == 2
    assert all(consulter_disponibilites(a)["disponible"] for a in resume["alternatives"])
    brouillon = resume["fichier"].read_text(encoding="utf-8")
    assert all(f"du {_fr(a['arrivee'])} au {_fr(a['depart'])}" in brouillon for a in resume["alternatives"])
    assert not (tmp_path / "devis").exists() or list((tmp_path / "devis").glob("*")) == []


def test_date_deduite_signalee_dans_le_brouillon(tmp_path):
    resume = traiter(fiche("demande_05", hypothese=True), tmp_path)
    assert "hypothèse" in resume["fichier"].read_text(encoding="utf-8")


def test_montant_invente_par_le_modele_rejete(tmp_path):
    client = FauxModele("Bonjour, nous vous offrons ce séjour pour 5 000 € seulement.")
    texte = traiter(fiche("demande_01"), tmp_path, client)["fichier"].read_text(encoding="utf-8")
    assert "5 000" not in texte and "9 346,00 €" in texte  # repli sur le modèle de texte, total issu du devis


def test_texte_du_modele_conserve_si_montant_exact(tmp_path):
    client = FauxModele("Bonjour, le total indicatif est de 9 346,00 € TTC.")
    texte = traiter(fiche("demande_01"), tmp_path, client)["fichier"].read_text(encoding="utf-8")
    assert "le total indicatif est de 9 346,00 € TTC" in texte


def test_une_erreur_n_arrete_pas_les_autres_demandes(tmp_path):
    def extraire(d, client=None):
        if d["id"] == "demande_01":
            raise RuntimeError("panne simulée")
        return fiche(d["id"])
    resumes = traiter_boite([demande("demande_01"), demande("demande_02")], client=FauxModele(""),
                            extraire=extraire, sortie=tmp_path)
    assert [r["id"] for r in resumes] == ["demande_02"]
