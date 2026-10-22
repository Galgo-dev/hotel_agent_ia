"""Serveur MCP local (stdio) : expose les outils de src/outils.py. Aucun outil d'envoi ni d'écriture du planning.

Lancement manuel : python -m src.serveur_mcp   (l'agent le démarre lui-même comme sous-processus).
"""
import functools

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from src import outils

serveur = MCPServer(
    "grand-cedre",
    instructions="Outils de traitement des demandes de groupe de l'hôtel Le Grand Cèdre. Planning en lecture seule, "
                 "montants calculés uniquement par calculer_devis, brouillons non envoyés écrits dans out/.")

OUTILS = (outils.lister_demandes, outils.lire_demande, outils.enregistrer_fiche, outils.consulter_disponibilites,
          outils.chercher_dates_alternatives, outils.calculer_devis, outils.ecrire_brouillon)


def _enregistrer(fonction):
    """Expose l'outil ; un refus prévu devient une ToolError, seule forme dont le message atteint le modèle."""
    @functools.wraps(fonction)
    def enveloppe(*args, **kwargs):
        try:
            return fonction(*args, **kwargs)
        except (outils.ErreurOutil, ValueError, KeyError) as erreur:
            raise ToolError(str(erreur)) from erreur
    return serveur.tool()(enveloppe)


for _fonction in OUTILS:
    _enregistrer(_fonction)

if __name__ == "__main__":
    serveur.run("stdio")
