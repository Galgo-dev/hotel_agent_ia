"""Calcul du devis indicatif à partir de la grille tarifaire (seul module qui produit des montants)."""
import re
import unicodedata
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

GRILLE = Path(__file__).resolve().parent.parent / "ressource" / "grille_tarifaire.md"
MOIS = {"janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
        "août": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12}
PRESTATIONS = {"petit": "petit_dejeuner", "dejeuner": "dejeuner", "diner": "diner", "pause": "pause_cafe"}
LIBELLES_REPAS = {"dejeuner": "Déjeuner buffet", "diner": "Dîner 3 services", "pause_cafe": "Pause café"}


class DemandeIncomplete(ValueError):
    """Dates ou effectif absents : aucun devis ne peut être calculé."""


def _norm(texte: str) -> str:
    """Minuscules sans accents, pour comparer les libellés."""
    texte = unicodedata.normalize("NFD", texte)
    return "".join(c for c in texte if not unicodedata.combining(c)).lower().strip()


def _lignes_tableau(texte: str, titre: str) -> list[list[str]]:
    """Renvoie les lignes de données du tableau situé sous le titre '## ...' donné."""
    lignes, dans_section = [], False
    for ligne in texte.splitlines():
        if ligne.startswith("## "):
            dans_section = ligne[3:].strip() == titre
        elif dans_section and ligne.startswith("|"):
            cellules = [c.strip() for c in ligne.strip("|").split("|")]
            if not set(cellules[0]) <= set("-: ") and cellules[0] not in ("Type", "Salle", "Prestation", "Saison"):
                lignes.append(cellules)
    return lignes


def _parse_periode(texte: str) -> tuple[date, date]:
    """Convertit 'du 6 au 31 janvier 2027' en (date de début, date de fin) incluses."""
    m = re.search(r"du (\d+)(?:er)?\s*(\w+)?\s*(\d{4})? au (\d+)\s+(\w+)\s+(\d{4})", texte)
    j1, mois1, an1, j2, mois2, an2 = m.groups()
    fin = date(int(an2), MOIS[mois2], int(j2))
    debut = date(int(an1 or an2), MOIS[mois1 or mois2], int(j1))
    return debut, fin


@lru_cache(maxsize=1)
def charger_grille() -> dict:
    """Lit grille_tarifaire.md et renvoie saisons, chambres, salles et repas."""
    texte = GRILLE.read_text(encoding="utf-8")
    saisons = {_norm(c[0]): _parse_periode(c[1]) for c in _lignes_tableau(texte, "Saisons")}
    chambres = {_norm(c[0]): {"capacite": int(c[1]), "personnes": int(c[2]), "prix": dict(zip(("basse", "haute", "intermediaire"), map(float, c[3:6])))}
                for c in _lignes_tableau(texte, "Chambres (prix par chambre et par nuit, petit-déjeuner exclu)")}
    salles = {_norm(c[0]): {"nom": c[0], "prix": float(c[2])}
              for c in _lignes_tableau(texte, "Salles de séminaire (à la journée, hors repas)")}
    repas = {PRESTATIONS[_norm(c[0]).split()[0].split("-")[0]]: float(c[2])
             for c in _lignes_tableau(texte, "Repas et petit-déjeuner")}
    return {"saisons": saisons, "chambres": chambres, "salles": salles, "repas": repas}


def saison_de(nuit: date) -> str:
    """Renvoie la saison (basse, haute, intermediaire) de la nuit datée donnée."""
    for nom, (debut, fin) in charger_grille()["saisons"].items():
        if debut <= nuit <= fin:
            return nom
    raise ValueError(f"La nuit du {nuit} n'est couverte par aucune saison de la grille")


def dates_sejour(fiche: dict) -> tuple[date, date]:
    """Valide les champs obligatoires et renvoie (arrivée, départ)."""
    manquants = [c for c in ("arrivee", "depart") if not fiche.get(c)]
    if not fiche.get("effectif"):
        manquants.append("effectif")
    if manquants:
        raise DemandeIncomplete(f"Champs manquants : {', '.join(manquants)}")
    arrivee, depart = date.fromisoformat(fiche["arrivee"]), date.fromisoformat(fiche["depart"])
    if depart <= arrivee:
        raise ValueError("La date de départ doit suivre la date d'arrivée")
    return arrivee, depart


def _ligne(libelle: str, quantite: int, prix: float) -> dict:
    return {"libelle": libelle, "quantite": quantite, "prix_unitaire": prix, "montant": round(quantite * prix, 2)}


def calculer_devis(fiche: dict) -> dict:
    """Calcule les lignes et le total du devis ; lève DemandeIncomplete si dates ou effectif manquent."""
    arrivee, depart = dates_sejour(fiche)
    grille = charger_grille()
    nuits = [arrivee + timedelta(days=i) for i in range((depart - arrivee).days)]
    lignes, logees = [], 0

    for type_ch, nombre in fiche.get("chambres", {}).items():
        if not nombre:
            continue
        info = grille["chambres"][_norm(type_ch)]
        logees += nombre * info["personnes"]
        par_saison: dict[str, int] = {}
        for nuit in nuits:
            par_saison[saison_de(nuit)] = par_saison.get(saison_de(nuit), 0) + 1
        for saison, nb_nuits in par_saison.items():
            lignes.append(_ligne(f"Chambre {type_ch} – saison {saison} ({nombre} ch. × {nb_nuits} nuit(s))",
                                 nombre * nb_nuits, info["prix"][saison]))

    for salle in fiche.get("salles", []):
        info = grille["salles"][_norm(salle["nom"])]
        lignes.append(_ligne(f"Salle {info['nom']} – {salle['date']}", 1, info["prix"]))

    for repas in fiche.get("repas", []):
        quantite = repas["personnes"] * repas.get("quantite", 1)
        lignes.append(_ligne(f"{LIBELLES_REPAS[repas['type']]} – {repas['date']} ({repas['personnes']} pers.)",
                             quantite, grille["repas"][repas["type"]]))

    if logees:
        lignes.append(_ligne(f"Petit-déjeuner ({logees} pers. × {len(nuits)} nuit(s))",
                             logees * len(nuits), grille["repas"]["petit_dejeuner"]))

    return {"lignes": lignes, "total": round(sum(l["montant"] for l in lignes), 2)}


def devis_markdown(fiche: dict, devis: dict) -> str:
    """Met en forme le devis en Markdown, une ligne par prestation."""
    rows = [f"| {l['libelle']} | {l['quantite']} | {l['prix_unitaire']:.2f} € | {l['montant']:.2f} € |"
            for l in devis["lignes"]]
    return "\n".join([
        f"# Devis indicatif – {fiche.get('client') or fiche['id']}", "",
        f"Séjour du {fiche['arrivee']} au {fiche['depart']} – {fiche['effectif']} personnes", "",
        "| Prestation | Quantité | Prix unitaire | Montant |", "|---|---|---|---|", *rows, "",
        f"**Total TTC : {devis['total']:.2f} €**", "",
        "Devis indicatif, sans remise, taxe de séjour non incluse. Aucune réservation n'est effectuée.", ""])
