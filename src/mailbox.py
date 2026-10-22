"""Lecture seule de la boîte de test : les courriels .eml de ressource/mails/."""
from email import policy
from email.parser import Parser
from pathlib import Path

DOSSIER_MAILS = Path(__file__).resolve().parent.parent / "ressource" / "mails"


def lire_demande(chemin: Path) -> dict:
    """Lit un fichier .eml et renvoie id, expéditeur, sujet et corps."""
    texte = Path(chemin).read_text(encoding="utf-8")
    message = Parser(policy=policy.default).parsestr(texte)
    corps = message.get_payload()  # texte brut : les .eml n'ont pas d'en-tête de charset
    return {
        "id": "_".join(chemin.stem.split("_")[:2]),
        "fichier": chemin.name,
        "expediteur": str(message["From"] or ""),
        "sujet": str(message["Subject"] or ""),
        "corps": corps.strip(),
    }


def lire_demandes(dossier: Path = DOSSIER_MAILS) -> list[dict]:
    """Renvoie toutes les demandes de la boîte, triées par nom de fichier."""
    return [lire_demande(p) for p in sorted(Path(dossier).glob("*.eml"))]
