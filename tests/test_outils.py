"""Tests des outils de l'agent : garde-fous appliqués par le code, sans modèle ni serveur MCP."""
import hashlib
import json

import pytest

from src import outils
from src.outils import ErreurOutil
from src.planning import PLANNING_CHAMBRES, PLANNING_SALLES, consulter_disponibilites, decaler_fiche

IDS = ["demande_01", "demande_04", "demande_05", "demande_08"]


def brut_mariage(**champs) -> dict:
    base = {"client": "Marie Test", "type_evenement": "mariage", "arrivee": "2026-11-06", "depart": "2026-11-08",
            "hypothese": False, "effectif": 60, "chambres": {"double": 12, "suite": 2},
            "salles": [{"nom": "Cèdre", "date": "2026-11-07"}],
            "repas": [{"type": "diner", "date": "2026-11-07", "personnes": 60, "quantite": 1}]}
    return {**base, **champs}


def brut_incompatible() -> dict:
    """11 au 13 décembre : 9 doubles libres seulement et Cèdre déjà prise le 12 (cas de la demande 08)."""
    return brut_mariage(arrivee="2026-12-11", depart="2026-12-13", effectif=45, chambres={"simple": 8, "double": 12},
                        salles=[{"nom": "Cèdre", "date": "2026-12-12"}],
                        repas=[{"type": "dejeuner", "date": "2026-12-12", "personnes": 45, "quantite": 1}])


@pytest.fixture(autouse=True)
def dossiers(tmp_path, monkeypatch):
    mails = tmp_path / "mails"
    mails.mkdir()
    for id_ in IDS:
        (mails / f"{id_}_test.eml").write_text(
            f"From: Client Test <client@example.org>\nSubject: Sujet {id_}\n\nBonjour, voici ma demande.\n", encoding="utf-8")
    monkeypatch.setenv("GC_MAILS", str(mails))
    monkeypatch.setenv("GC_SORTIE", str(tmp_path / "out"))
    return tmp_path / "out"


def empreintes() -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in (PLANNING_CHAMBRES, PLANNING_SALLES)]


def test_courriel_renvoye_comme_donnee_et_id_inconnu_refuse():
    assert [d["id"] for d in outils.lister_demandes()] == IDS
    assert outils.lire_demande("demande_01")["courriel"].startswith("<courriel>\n")
    for id_inconnu in ("demande_99", "../decisions"):
        with pytest.raises(ErreurOutil):
            outils.lire_demande(id_inconnu)


def test_fiche_validee_par_le_code_et_enregistree(dossiers):
    fiche = outils.enregistrer_fiche("demande_01", brut_mariage(arrivee="vendredi 6 novembre"))
    assert fiche["arrivee"] is None and "arrivee" in fiche["champs_manquants"]  # jamais de date inventée
    assert json.loads((dossiers / "fiches" / "demande_01.json").read_text(encoding="utf-8"))["id"] == "demande_01"
    assert outils.enregistrer_fiche("demande_01", brut_mariage())["champs_manquants"] == []


def test_total_du_devis_calcule_par_le_code():
    outils.enregistrer_fiche("demande_01", brut_mariage())
    devis = outils.calculer_devis("demande_01")
    assert devis["total"] == 9346 and devis["total_formate"] == "9 346,00 €"


def test_aucun_calcul_ni_planning_sur_fiche_incomplete():
    outils.enregistrer_fiche("demande_04", brut_mariage(depart=None))
    for outil in (outils.calculer_devis, outils.consulter_disponibilites, outils.chercher_dates_alternatives):
        with pytest.raises(ErreurOutil, match="incomplète"):
            outil("demande_04")


def test_proposition_avec_devis_joint_et_signature_unique(dossiers):
    outils.enregistrer_fiche("demande_01", brut_mariage())
    resume = outils.ecrire_brouillon("demande_01", "proposition",
                                     "Bonjour,\nLe total indicatif est de 9 346,00 € TTC.\n\nCordialement,\nMon nom")
    assert resume["total"] == 9346 and resume["devis_joint"]
    texte = (dossiers / resume["fichier"]).read_text(encoding="utf-8")
    assert "**Pièce jointe :** devis/demande_01.md" in texte and "Mon nom" not in texte
    assert texte.count("Service commercial – Le Grand Cèdre") == 1
    assert (dossiers / "devis" / "demande_01.md").exists()


def test_type_de_reponse_incoherent_refuse(dossiers):
    outils.enregistrer_fiche("demande_04", brut_mariage(arrivee=None, depart=None))
    with pytest.raises(ErreurOutil, match="precisions"):
        outils.ecrire_brouillon("demande_04", "proposition", "Bonjour, voici notre offre.")
    outils.enregistrer_fiche("demande_08", brut_incompatible())
    with pytest.raises(ErreurOutil, match="alternatives"):
        outils.ecrire_brouillon("demande_08", "proposition", "Bonjour, tout est disponible.")
    resume = outils.ecrire_brouillon("demande_08", "alternatives", "Bonjour, ces dates ne sont pas disponibles.")
    assert not resume["devis_joint"] and not (dossiers / "devis").exists()


def test_montant_invente_refuse():
    outils.enregistrer_fiche("demande_01", brut_mariage())
    with pytest.raises(ErreurOutil, match="Montant"):
        outils.ecrire_brouillon("demande_01", "proposition", "Bonjour, ce séjour vous coûtera 5 000 €.")
    outils.enregistrer_fiche("demande_04", brut_mariage(arrivee=None, depart=None))
    with pytest.raises(ErreurOutil, match="aucun montant"):
        outils.ecrire_brouillon("demande_04", "precisions", "Bonjour, le total sera de 9 346,00 €.")


def test_dates_deduites_a_faire_confirmer(dossiers):
    outils.enregistrer_fiche("demande_05", brut_mariage(hypothese=True))
    with pytest.raises(ErreurOutil, match="confirmer"):
        outils.ecrire_brouillon("demande_05", "proposition", "Bonjour, total de 9 346,00 €.")
    resume = outils.ecrire_brouillon("demande_05", "proposition", "Bonjour, total de 9 346,00 €. Merci de confirmer ces dates.")
    assert "hypothèse" in (dossiers / resume["fichier"]).read_text(encoding="utf-8")


def test_dates_alternatives_reellement_libres(dossiers):
    fiche = outils.enregistrer_fiche("demande_08", brut_incompatible())
    assert not consulter_disponibilites(fiche)["disponible"]
    alternatives = outils.chercher_dates_alternatives("demande_08", 2)
    assert len(alternatives) == 2
    assert all(consulter_disponibilites(decaler_fiche(fiche, a["decalage_jours"]))["disponible"] for a in alternatives)


def test_planning_jamais_modifie():
    avant = empreintes()
    outils.enregistrer_fiche("demande_08", brut_incompatible())
    outils.consulter_disponibilites("demande_08")
    outils.chercher_dates_alternatives("demande_08")
    outils.ecrire_brouillon("demande_08", "alternatives", "Bonjour, ces dates ne sont pas disponibles.")
    outils.enregistrer_fiche("demande_01", brut_mariage())
    outils.calculer_devis("demande_01")
    assert empreintes() == avant
