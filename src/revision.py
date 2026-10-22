"""Relecture des brouillons par le service commercial : consigne la décision, n'envoie rien."""
import json
import shutil
from datetime import datetime
from pathlib import Path

from src.brouillons import SORTIE

DECISIONS = ("valide", "rejete")


def lire_decisions(sortie: Path = SORTIE) -> dict:
    """Lit out/decisions.json (vide si le fichier n'existe pas encore)."""
    chemin = Path(sortie) / "decisions.json"
    return json.loads(chemin.read_text(encoding="utf-8")) if chemin.exists() else {}


def lister_brouillons(sortie: Path = SORTIE) -> list[dict]:
    """Liste les brouillons de out/brouillons/ avec leur devis joint et leur décision éventuelle."""
    sortie, decisions, resultat = Path(sortie), lire_decisions(sortie), []
    for chemin in sorted((sortie / "brouillons").glob("*.md")):
        id_demande, _, type_reponse = chemin.stem.rpartition("_")
        devis = sortie / "devis" / f"{id_demande}.md"
        resultat.append({
            "id": id_demande, "type": type_reponse, "fichier": chemin.name,
            "contenu": chemin.read_text(encoding="utf-8"),
            "devis": devis.read_text(encoding="utf-8") if devis.exists() else None,
            "decision": decisions.get(id_demande, {}).get("decision"),
        })
    return resultat


def enregistrer_decision(id_demande: str, decision: str, sortie: Path = SORTIE) -> None:
    """Consigne 'valide' ou 'rejete' pour un brouillon existant ; un brouillon validé est copié dans out/valides/."""
    sortie = Path(sortie)
    if decision not in DECISIONS:
        raise ValueError(f"Décision inconnue : {decision!r}")
    brouillon = next((b for b in lister_brouillons(sortie) if b["id"] == id_demande), None)
    if brouillon is None:
        raise ValueError(f"Aucun brouillon pour la demande {id_demande!r}")

    decisions = lire_decisions(sortie)
    decisions[id_demande] = {"decision": decision, "date": datetime.now().isoformat(timespec="seconds")}
    (sortie / "decisions.json").write_text(json.dumps(decisions, ensure_ascii=False, indent=2), encoding="utf-8")

    copie = sortie / "valides" / brouillon["fichier"]
    if decision == "valide":
        copie.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sortie / "brouillons" / brouillon["fichier"], copie)
    else:
        copie.unlink(missing_ok=True)
