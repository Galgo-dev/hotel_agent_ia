"""Écriture des fiches, devis et brouillons : seul module qui écrit des fichiers, uniquement dans out/. Aucun envoi."""
import json
import re
from pathlib import Path

SORTIE = Path(__file__).resolve().parent.parent / "out"
SIGNATURE = "Cordialement,\n\nService commercial – Le Grand Cèdre"
TITRES = {"precisions": "demande de précisions", "proposition": "proposition", "alternatives": "dates alternatives"}


def montants_valides(texte: str, autorises: set[str]) -> bool:
    """Vrai si tout montant en € du texte figure parmi les chiffres autorisés (ex. {'934600'})."""
    return all(re.sub(r"\D", "", m) in autorises for m in re.findall(r"\d[\d\s.,]*\s?€", texte))


def ecrire_fiche(fiche: dict, sortie: Path = SORTIE) -> Path:
    """Écrit la fiche JSON dans out/fiches/."""
    chemin = Path(sortie) / "fiches" / f"{fiche['id']}.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(fiche, ensure_ascii=False, indent=2), encoding="utf-8")
    return chemin


def ecrire_devis(id_demande: str, devis_md: str, sortie: Path = SORTIE) -> Path:
    """Écrit le devis Markdown dans out/devis/."""
    chemin = Path(sortie) / "devis" / f"{id_demande}.md"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(devis_md, encoding="utf-8")
    return chemin


def ecrire_brouillon(demande: dict, fiche: dict, type_reponse: str, corps: str, devis_md: str | None = None,
                     sortie: Path = SORTIE) -> Path:
    """Écrit le brouillon dans out/brouillons/ (avec le devis en pièce jointe pour une proposition)."""
    entete = [f"# Brouillon – {fiche['id']} ({TITRES[type_reponse]})", "",
              "> BROUILLON NON ENVOYÉ : à relire par le service commercial avant tout envoi.", "",
              f"**À :** {demande['expediteur']}", f"**Objet :** Re: {demande['sujet']}"]
    if devis_md:
        entete.append(f"**Pièce jointe :** {ecrire_devis(fiche['id'], devis_md, sortie).relative_to(Path(sortie)).as_posix()}")
    if fiche.get("hypothese"):
        entete += ["", "> ⚠ Note interne : les dates ont été déduites du courriel (hypothèse) ; à faire confirmer par le client."]
    chemin = Path(sortie) / "brouillons" / f"{fiche['id']}_{type_reponse}.md"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("\n".join(entete) + f"\n\n---\n\n{corps}\n\n{SIGNATURE}\n", encoding="utf-8")
    return chemin
