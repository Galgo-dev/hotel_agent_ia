"""Tests du serveur MCP : démarrage réel en sous-processus stdio et appels par un client MCP (sans modèle)."""
import asyncio
import contextlib
import hashlib
import json
import sys
from pathlib import Path

import pytest
from mcp import Client, StdioServerParameters

from src.planning import PLANNING_CHAMBRES, PLANNING_SALLES

RACINE = Path(__file__).resolve().parent.parent
OUTILS_ATTENDUS = {"lister_demandes", "lire_demande", "enregistrer_fiche", "consulter_disponibilites",
                   "chercher_dates_alternatives", "calculer_devis", "ecrire_brouillon"}
MARIAGE = {"client": "Marie Test", "type_evenement": "mariage", "arrivee": "2026-11-06", "depart": "2026-11-08",
           "hypothese": False, "effectif": 60, "chambres": {"double": 12, "suite": 2},
           "salles": [{"nom": "Cèdre", "date": "2026-11-07"}],
           "repas": [{"type": "diner", "date": "2026-11-07", "personnes": 60, "quantite": 1}]}


@pytest.fixture
def env(tmp_path):
    mails = tmp_path / "mails"
    mails.mkdir()
    for id_ in ("demande_01", "demande_04"):
        (mails / f"{id_}_test.eml").write_text(
            f"From: Client Test <client@example.org>\nSubject: Sujet {id_}\n\nBonjour, voici ma demande.\n", encoding="utf-8")
    return {"GC_MAILS": str(mails), "GC_SORTIE": str(tmp_path / "out")}


def executer(scenario, env):
    """Démarre le serveur MCP (python -m src.serveur_mcp) et exécute le scénario avec un client connecté."""
    async def principal():
        params = StdioServerParameters(command=sys.executable, args=["-m", "src.serveur_mcp"], cwd=RACINE, env=env)
        async with Client(params) as client:
            return await scenario(client)
    return asyncio.run(principal())


def contenu(resultat):
    """Décode la réponse d'un outil : texte brut en cas d'erreur, JSON sinon."""
    texte = "\n".join(bloc.text for bloc in resultat.content)
    return texte if resultat.is_error else json.loads(texte)


def empreintes() -> list[str]:
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in (PLANNING_CHAMBRES, PLANNING_SALLES)]


def test_expose_exactement_les_sept_outils_sans_envoi_ni_ecriture_planning(env):
    async def scenario(client):
        return (await client.list_tools()).tools
    outils = executer(scenario, env)
    assert {t.name for t in outils} == OUTILS_ATTENDUS
    assert not any(mot in t.name for t in outils for mot in ("envoy", "send", "planning", "reserv", "bloqu"))
    devis = next(t for t in outils if t.name == "calculer_devis")
    assert list(devis.input_schema["properties"]) == ["id_demande"]  # aucun paramètre de remise


def test_lecture_de_la_boite_de_test(env):
    async def scenario(client):
        liste = await client.call_tool("lister_demandes", {})
        lue = await client.call_tool("lire_demande", {"id_demande": "demande_01"})
        return liste, lue
    liste, lue = executer(scenario, env)
    assert "demande_04" in "\n".join(b.text for b in liste.content)
    assert contenu(lue)["courriel"].startswith("<courriel>")


def test_devis_calcule_via_mcp(env):
    async def scenario(client):
        await client.call_tool("enregistrer_fiche", {"id_demande": "demande_01", "fiche": MARIAGE})
        return await client.call_tool("calculer_devis", {"id_demande": "demande_01"})
    devis = contenu(executer(scenario, env))
    assert devis["total"] == 9346 and devis["total_formate"] == "9 346,00 €"


def test_refus_transmis_au_modele_avec_leur_motif(env):
    async def scenario(client):
        await client.call_tool("enregistrer_fiche", {"id_demande": "demande_04", "fiche": {**MARIAGE, "depart": None}})
        sans_devis = await client.call_tool("calculer_devis", {"id_demande": "demande_04"})
        await client.call_tool("enregistrer_fiche", {"id_demande": "demande_01", "fiche": MARIAGE})
        prix_invente = await client.call_tool("ecrire_brouillon", {
            "id_demande": "demande_01", "type_reponse": "proposition", "corps": "Bonjour, ce séjour coûte 5 000 €."})
        return sans_devis, prix_invente
    sans_devis, prix_invente = executer(scenario, env)
    assert sans_devis.is_error and "incomplète" in contenu(sans_devis)
    assert prix_invente.is_error and "Montant en € non autorisé" in contenu(prix_invente)


def test_brouillon_ecrit_et_planning_inchange(env):
    avant = empreintes()

    async def scenario(client):
        await client.call_tool("enregistrer_fiche", {"id_demande": "demande_01", "fiche": MARIAGE})
        dispo = await client.call_tool("consulter_disponibilites", {"id_demande": "demande_01"})
        brouillon = await client.call_tool("ecrire_brouillon", {
            "id_demande": "demande_01", "type_reponse": "proposition", "corps": "Bonjour, le total est de 9 346,00 €."})
        return dispo, brouillon
    dispo, brouillon = executer(scenario, env)
    assert contenu(dispo)["disponible"] is True
    assert contenu(brouillon)["devis_joint"] is True
    assert (Path(env["GC_SORTIE"]) / "brouillons" / "demande_01_proposition.md").exists()
    assert empreintes() == avant
