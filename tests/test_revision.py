"""Tests de la relecture : décisions consignées, copie des brouillons validés, page locale protégée."""
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from src.brouillons import ecrire_brouillon
from src.interface import creer_serveur, page
from src.revision import enregistrer_decision, lire_decisions, lister_brouillons

DEMANDE = {"expediteur": "Client <client@example.org>", "sujet": "Sujet"}


@pytest.fixture
def sortie(tmp_path):
    ecrire_brouillon(DEMANDE, {"id": "demande_01"}, "proposition", "Bonjour, total 9 346,00 €.", "# Devis", tmp_path)
    ecrire_brouillon(DEMANDE, {"id": "demande_04"}, "precisions", "<script>alert(1)</script>", None, tmp_path)
    return tmp_path


@pytest.fixture
def serveur(sortie):
    srv, token = creer_serveur(sortie)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", token
    srv.shutdown()
    srv.server_close()


def poster(url: str, **champs) -> int:
    requete = urllib.request.Request(url + "/decision", urllib.parse.urlencode(champs).encode())
    try:
        with urllib.request.urlopen(requete) as reponse:
            return reponse.status
    except urllib.error.HTTPError as erreur:
        return erreur.code


def test_brouillons_listes_en_attente_avec_devis(sortie):
    brouillons = lister_brouillons(sortie)
    assert [(b["id"], b["type"], b["decision"]) for b in brouillons] == [
        ("demande_01", "proposition", None), ("demande_04", "precisions", None)]
    assert brouillons[0]["devis"] == "# Devis" and brouillons[1]["devis"] is None


def test_validation_copie_le_brouillon_dans_valides(sortie):
    enregistrer_decision("demande_01", "valide", sortie)
    assert (sortie / "valides" / "demande_01_proposition.md").exists()
    assert lire_decisions(sortie)["demande_01"]["decision"] == "valide"


def test_rejet_apres_validation_retire_la_copie(sortie):
    enregistrer_decision("demande_01", "valide", sortie)
    enregistrer_decision("demande_01", "rejete", sortie)
    assert not (sortie / "valides" / "demande_01_proposition.md").exists()
    assert lister_brouillons(sortie)[0]["decision"] == "rejete"


@pytest.mark.parametrize("id_demande, decision", [("../decisions", "valide"), ("demande_99", "valide"),
                                                  ("demande_01", "envoyer")])
def test_decision_invalide_refusee(sortie, id_demande, decision):
    with pytest.raises(ValueError):
        enregistrer_decision(id_demande, decision, sortie)


def test_page_echappe_le_contenu_des_brouillons(sortie):
    html = page(lister_brouillons(sortie), "jeton")
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "0 validé(s), 0 rejeté(s), 2 en attente" in html


def test_serveur_affiche_et_enregistre_avec_le_bon_jeton(serveur, sortie):
    url, token = serveur
    with urllib.request.urlopen(url + "/") as reponse:
        assert reponse.status == 200 and token in reponse.read().decode("utf-8")
    assert poster(url, token=token, id="demande_01", decision="valide") == 200  # redirection suivie vers la page
    assert lire_decisions(sortie)["demande_01"]["decision"] == "valide"


def test_serveur_refuse_un_jeton_incorrect(serveur, sortie):
    url, _ = serveur
    assert poster(url, token="faux", id="demande_01", decision="valide") == 403
    assert lire_decisions(sortie) == {}
