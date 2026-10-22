"""Boucle principale : extraction, disponibilités, devis, brouillon. Ne réserve ni n'envoie rien."""
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from src.brouillons import SORTIE, ecrire_brouillon, ecrire_fiche, rediger_corps
from src.devis import DemandeIncomplete, calculer_devis, devis_markdown
from src.extraction import extraire_fiche
from src.mailbox import lire_demandes
from src.planning import chercher_dates_alternatives, consulter_disponibilites

LIBELLES_MANQUANTS = {"arrivee": "la date d'arrivée", "depart": "la date de départ", "effectif": "le nombre de personnes",
                      "salles.date": "la ou les dates d'utilisation de la salle", "repas.date": "la ou les dates des repas"}


def _montant(valeur: float) -> str:
    """Formate un montant à la française : 9 346,00 €."""
    return f"{valeur:,.2f}".replace(",", " ").replace(".", ",") + " €"


def analyser(fiche: dict) -> dict:
    """Choisit le type de réponse et rassemble devis, conflits et alternatives."""
    if not fiche["champs_manquants"]:
        try:
            dispo = consulter_disponibilites(fiche)
            if dispo["disponible"]:
                return {"type": "proposition", "devis": calculer_devis(fiche)}
            return {"type": "alternatives", "conflits": dispo["conflits"],
                    "alternatives": chercher_dates_alternatives(fiche)}
        except DemandeIncomplete:
            pass
    return {"type": "precisions"}


def construire_faits(fiche: dict, analyse: dict) -> tuple[dict, set[str]]:
    """Faits transmis à la rédaction, et chiffres de montants autorisés dans le texte."""
    faits = {"client": fiche["client"], "type_evenement": fiche["type_evenement"]}
    autorises: set[str] = set()
    if analyse["type"] == "precisions":
        faits["informations_manquantes"] = [LIBELLES_MANQUANTS.get(c, c) for c in fiche["champs_manquants"]]
        faits["dates_connues"] = {"arrivee": fiche["arrivee"], "depart": fiche["depart"]}
    elif analyse["type"] == "proposition":
        total = _montant(analyse["devis"]["total"])
        autorises = {"".join(c for c in total if c.isdigit())}
        faits.update(arrivee=fiche["arrivee"], depart=fiche["depart"], effectif=fiche["effectif"], total_ttc=total,
                     chambres={k: v for k, v in fiche["chambres"].items() if v}, salles=fiche["salles"],
                     repas=fiche["repas"], dates_deduites=fiche["hypothese"])
    else:
        faits.update(dates_demandees={"arrivee": fiche["arrivee"], "depart": fiche["depart"]},
                     motifs_indisponibilite=analyse["conflits"],
                     alternatives=[{"arrivee": a["arrivee"], "depart": a["depart"]} for a in analyse["alternatives"]])
    return faits, autorises


def traiter_demande(demande: dict, client=None, extraire=extraire_fiche, sortie: Path = SORTIE) -> dict:
    """Traite une demande de bout en bout et renvoie un résumé (id, type de réponse, total, fichier)."""
    fiche = extraire(demande, client=client)
    ecrire_fiche(fiche, sortie)
    analyse = analyser(fiche)
    faits, autorises = construire_faits(fiche, analyse)
    corps = rediger_corps(analyse["type"], faits, autorises, client)
    devis_md = devis_markdown(fiche, analyse["devis"]) if analyse["type"] == "proposition" else None
    fichier = ecrire_brouillon(demande, fiche, analyse["type"], corps, devis_md, sortie)
    return {"id": fiche["id"], "type": analyse["type"], "fichier": fichier,
            "total": analyse["devis"]["total"] if devis_md else None,
            "alternatives": analyse.get("alternatives", [])}


def traiter_boite(demandes: list[dict] | None = None, client=None, extraire=extraire_fiche,
                  sortie: Path = SORTIE) -> list[dict]:
    """Traite toute la boîte ; une erreur sur une demande n'arrête pas les suivantes."""
    load_dotenv()
    demandes = lire_demandes() if demandes is None else demandes
    client = client or anthropic.Anthropic()
    resumes = []
    for demande in demandes:
        try:
            resume = traiter_demande(demande, client, extraire, sortie)
        except Exception as erreur:  # une demande en échec ne doit pas bloquer les autres
            print(f"{demande['id']} | ERREUR | {type(erreur).__name__}: {erreur}")
            continue
        total = f"{resume['total']:.2f} €" if resume["total"] is not None else "-"
        print(f"{resume['id']} | {resume['type']:<12} | total {total:>11} | {Path(resume['fichier']).as_posix()}")
        resumes.append(resume)
    return resumes
