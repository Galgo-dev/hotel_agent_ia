"""Tests de l'agent : modèle scripté et outils réels (garde-fous compris) appelés en direct, sans réseau."""
import json
from types import SimpleNamespace

import pytest

from src import agent, outils
from src.serveur_mcp import OUTILS

IDS = ["demande_01", "demande_04", "demande_08"]
MARIAGE = {"client": "Marie Test", "type_evenement": "mariage", "arrivee": "2026-11-06", "depart": "2026-11-08",
           "hypothese": False, "effectif": 60, "chambres": {"double": 12, "suite": 2},
           "salles": [{"nom": "Cèdre", "date": "2026-11-07"}],
           "repas": [{"type": "diner", "date": "2026-11-07", "personnes": 60, "quantite": 1}]}
INCOMPATIBLE = {**MARIAGE, "arrivee": "2026-12-11", "depart": "2026-12-13", "effectif": 45,
                "chambres": {"simple": 8, "double": 12}, "salles": [{"nom": "Cèdre", "date": "2026-12-12"}],
                "repas": [{"type": "dejeuner", "date": "2026-12-12", "personnes": 45, "quantite": 1}]}


def appel(nom: str, **args):
    """Bloc tool_use que le faux modèle demande."""
    return SimpleNamespace(type="tool_use", id=f"id_{nom}", name=nom, input=args)


def fin(texte="Brouillon écrit."):
    return [SimpleNamespace(type="text", text=texte)]


class FauxModele:
    """Rejoue une suite de réponses ; garde les arguments et les messages reçus à chaque tour."""
    def __init__(self, *tours):
        self.tours, self.appels = list(tours), []
        self.messages = self

    async def create(self, **kwargs):
        self.appels.append({**kwargs, "messages": list(kwargs["messages"])})
        tour = self.tours.pop(0) if self.tours else fin()
        if isinstance(tour, Exception):
            raise tour
        return SimpleNamespace(content=tour)


class FausseSession:
    """Appelle directement les fonctions de outils.py, comme le ferait le serveur MCP."""
    def __init__(self):
        self.fonctions = {f.__name__: f for f in OUTILS}

    async def list_tools(self):
        return SimpleNamespace(tools=[SimpleNamespace(name=n, description=f.__doc__, input_schema={"type": "object"})
                                      for n, f in self.fonctions.items()])

    async def call_tool(self, nom, arguments):
        if nom not in self.fonctions:
            return self._reponse([f"Outil inconnu : {nom}"], True)
        try:
            resultat = self.fonctions[nom](**arguments)
        except (outils.ErreurOutil, ValueError, KeyError) as erreur:
            return self._reponse([str(erreur)], True)
        elements = resultat if isinstance(resultat, list) else [resultat]
        return self._reponse([json.dumps(e, ensure_ascii=False) for e in elements], False)

    @staticmethod
    def _reponse(textes, erreur):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=t) for t in textes], is_error=erreur)


@pytest.fixture(autouse=True)
def dossiers(tmp_path, monkeypatch):
    mails = tmp_path / "mails"
    mails.mkdir()
    for id_ in IDS:
        (mails / f"{id_}_test.eml").write_text(
            f"From: Client Test <client@example.org>\nSubject: Sujet {id_}\n\nBonjour, voici ma demande.\n", encoding="utf-8")
    monkeypatch.setenv("GC_MAILS", str(mails))
    monkeypatch.setenv("GC_SORTIE", str(tmp_path / "out"))
    monkeypatch.setenv("MODEL", "modele-de-test")
    return tmp_path / "out"


def lancer(modele, ids=None):
    return agent.traiter_boite(ids=ids, llm=modele, session=FausseSession())


def test_parcours_complet_proposition_avec_devis(dossiers):
    modele = FauxModele(
        [appel("lire_demande", id_demande="demande_01")],
        [appel("enregistrer_fiche", id_demande="demande_01", fiche=MARIAGE)],
        [appel("consulter_disponibilites", id_demande="demande_01")],
        [appel("calculer_devis", id_demande="demande_01")],
        [appel("ecrire_brouillon", id_demande="demande_01", type_reponse="proposition",
               corps="Bonjour, le total indicatif est de 9 346,00 € TTC.")],
        fin())
    [resume] = lancer(modele, ["demande_01"])
    assert (resume["type"], resume["total"]) == ("proposition", 9346)
    assert (dossiers / "devis" / "demande_01.md").exists() and (dossiers / resume["fichier"]).exists()
    premier = modele.appels[0]
    assert {t["name"] for t in premier["tools"]} == {f.__name__ for f in OUTILS}
    assert "DONNÉE" in premier["system"] and "remise" in premier["system"]


def test_refus_d_un_outil_renvoye_au_modele_qui_se_corrige(dossiers):
    modele = FauxModele(
        [appel("enregistrer_fiche", id_demande="demande_01", fiche=MARIAGE)],
        [appel("ecrire_brouillon", id_demande="demande_01", type_reponse="proposition", corps="Bonjour, ce séjour coûte 5 000 €.")],
        [appel("ecrire_brouillon", id_demande="demande_01", type_reponse="proposition", corps="Bonjour, total : 9 346,00 €.")],
        fin())
    [resume] = lancer(modele, ["demande_01"])
    refus = modele.appels[2]["messages"][-1]["content"][0]  # résultat de l'outil vu par le modèle au 3e tour
    assert refus["is_error"] and "Montant en € non autorisé" in refus["content"]
    assert resume["type"] == "proposition" and resume["total"] == 9346


def test_demande_incomplete_sans_devis(dossiers):
    modele = FauxModele(
        [appel("enregistrer_fiche", id_demande="demande_04", fiche={**MARIAGE, "depart": None})],
        [appel("calculer_devis", id_demande="demande_04")],
        [appel("ecrire_brouillon", id_demande="demande_04", type_reponse="precisions", corps="Bonjour, quelle est votre date de départ ?")],
        fin())
    [resume] = lancer(modele, ["demande_04"])
    assert modele.appels[2]["messages"][-1]["content"][0]["is_error"]  # le devis a été refusé par l'outil
    assert resume["type"] == "precisions" and not (dossiers / "devis").exists()


def test_demande_incompatible_recoit_des_alternatives_liees_au_planning(dossiers):
    modele = FauxModele(
        [appel("enregistrer_fiche", id_demande="demande_08", fiche=INCOMPATIBLE)],
        [appel("chercher_dates_alternatives", id_demande="demande_08")],
        [appel("ecrire_brouillon", id_demande="demande_08", type_reponse="alternatives", corps="Bonjour, ces dates sont indisponibles.")],
        fin())
    [resume] = lancer(modele, ["demande_08"])
    assert resume["type"] == "alternatives" and len(resume["alternatives"]) == 2
    assert not (dossiers / "devis").exists()


def test_aucun_outil_d_envoi_meme_si_le_modele_en_demande_un(dossiers):
    modele = FauxModele(
        [appel("envoyer_courriel", destinataire="client@example.org", corps="Bonjour")],
        fin("Impossible d'envoyer."))
    [resume] = lancer(modele, ["demande_01"])
    assert modele.appels[1]["messages"][-1]["content"][0]["is_error"]
    assert resume["type"] is None and not dossiers.exists()


def test_boucle_bornee(dossiers):
    modele = FauxModele(*[[appel("lister_demandes")] for _ in range(agent.MAX_TOURS + 5)])
    [resume] = lancer(modele, ["demande_01"])
    assert resume["tours"] == agent.MAX_TOURS and resume["type"] is None


def test_une_panne_n_arrete_pas_les_autres_demandes(dossiers):
    modele = FauxModele(
        RuntimeError("panne simulée"),
        [appel("enregistrer_fiche", id_demande="demande_04", fiche={**MARIAGE, "depart": None})],
        [appel("ecrire_brouillon", id_demande="demande_04", type_reponse="precisions", corps="Bonjour, quelle est votre date de départ ?")],
        fin())
    premier, second = lancer(modele, ["demande_01", "demande_04"])
    assert "panne simulée" in premier["erreur"] and second["type"] == "precisions"


def test_liste_des_demandes_demandee_a_l_outil_mcp(dossiers):
    modele = FauxModele(*[fin() for _ in IDS])
    resumes = lancer(modele)
    assert [r["id"] for r in resumes] == IDS
