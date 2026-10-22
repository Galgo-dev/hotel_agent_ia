"""Exécute les 10 cas de test de la fiche de cadrage (tests/cas_de_test.json) et les affiche dans le terminal.

Pour chaque cas : sujet, entrée, sortie obtenue, résultat attendu et vérifications.
Usage : python lancer_cas_de_test.py [numéros de cas...] [--garder]
  --garder : conserve les fichiers produits dans out/cas_de_test/ (sinon dossier temporaire supprimé).
L'agent (client MCP) traite les 10 courriels avec le serveur MCP local : plusieurs appels au modèle par cas.
MODEL et ANTHROPIC_API_KEY doivent être définis dans .env.
"""
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from src.agent import traiter_boite
from src.brouillons import SORTIE
from src.planning import PLANNING_CHAMBRES, PLANNING_SALLES, consulter_disponibilites, decaler_fiche

FICHIER_CAS = Path(__file__).resolve().parent / "tests" / "cas_de_test.json"
LARGEUR = 78


def empreintes() -> list[str]:
    """Hachages des fichiers de planning, pour prouver qu'ils ne changent pas."""
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in (PLANNING_CHAMBRES, PLANNING_SALLES)]


def id_cas(cas: dict) -> str:
    return f"cas_{cas['numero']:02d}"


def ecrire_courriel(cas: dict, mails: Path) -> None:
    """Dépose le courriel du cas dans la boîte de test temporaire lue par le serveur MCP."""
    c = cas["courriel"]
    (mails / f"{id_cas(cas)}_test.eml").write_text(
        f"From: {c['expediteur']}\nTo: Service commercial <reservations@grand-cedre.example>\n"
        f"Subject: {c['sujet']}\n\n{c['corps']}\n", encoding="utf-8")


def recueillir(cas: dict, resume: dict, sortie: Path, planning_identique: bool) -> dict:
    """Rassemble ce que l'agent a produit pour le cas ; lève une erreur si la fiche ou le brouillon manquent."""
    id_ = id_cas(cas)
    if resume.get("erreur"):
        raise RuntimeError(resume["erreur"])
    fiche = sortie / "fiches" / f"{id_}.json"
    if not fiche.exists() or not resume["fichier"]:
        raise RuntimeError("l'agent n'a pas enregistré de fiche ou n'a pas écrit de brouillon")
    devis = sortie / "devis" / f"{id_}.md"
    return {
        "resume": resume,
        "fiche": json.loads(fiche.read_text(encoding="utf-8")),
        "brouillon": (sortie / resume["fichier"]).read_text(encoding="utf-8"),
        "devis": devis.read_text(encoding="utf-8") if devis.exists() else None,
        "planning_identique": planning_identique,
    }


def _sous_ensemble(attendu, obtenu) -> bool:
    """Vrai si `obtenu` contient au moins les valeurs de `attendu` (listes comparées sans tenir compte de l'ordre)."""
    if isinstance(attendu, dict):
        return isinstance(obtenu, dict) and all(k in obtenu and _sous_ensemble(v, obtenu[k]) for k, v in attendu.items())
    if isinstance(attendu, list):
        cle = lambda liste: sorted(json.dumps(x, sort_keys=True, ensure_ascii=False) for x in liste)
        return isinstance(obtenu, list) and cle(attendu) == cle(obtenu)
    return attendu == obtenu


def verifier(spec: dict, res: dict) -> list[tuple[bool, str]]:
    """Évalue les vérifications du cas et renvoie une liste (réussi, libellé)."""
    resume, fiche, brouillon, devis = res["resume"], res["fiche"], res["brouillon"], res["devis"]
    controles: list[tuple[bool, str]] = []
    for champ, attendu in spec.get("fiche", {}).items():
        controles.append((_sous_ensemble(attendu, fiche.get(champ)), f"fiche.{champ} = {json.dumps(attendu, ensure_ascii=False)}"))
    if "type_reponse" in spec:
        attendus = [spec["type_reponse"]] if isinstance(spec["type_reponse"], str) else spec["type_reponse"]
        controles.append((resume["type"] in attendus, f"type de réponse : {' ou '.join(attendus)}"))
    if "devis" in spec:
        controles.append(((devis is not None) == spec["devis"], "devis en pièce jointe" if spec["devis"] else "aucun devis"))
    if "total" in spec:
        controles.append((resume["total"] is not None and abs(resume["total"] - spec["total"]) < 0.005,
                          f"total = calcul manuel ({spec['total']:.2f} €)"))
    for champ in spec.get("manquants_contient", []):
        controles.append((champ in fiche["champs_manquants"], f"champ signalé manquant : {champ}"))
    if "hypothese" in spec:
        controles.append((fiche["hypothese"] == spec["hypothese"], f"hypothese = {spec['hypothese']}"))
    if spec.get("alternatives_libres"):
        alternatives = resume["alternatives"]
        libres = bool(alternatives) and all(
            consulter_disponibilites(decaler_fiche(fiche, a["decalage_jours"]))["disponible"] for a in alternatives)
        controles.append((libres, f"{len(alternatives)} alternative(s), toutes libres dans le planning"))
    for motif in spec.get("devis_contient", []):
        controles.append((devis is not None and re.search(motif, devis, re.I) is not None, f"devis contient /{motif}/"))
    for motif in spec.get("devis_ne_contient", []):
        controles.append((devis is None or re.search(motif, devis, re.I) is None, f"devis ne contient pas /{motif}/"))
    if spec.get("texte_contient"):
        trouve = any(re.search(m, brouillon, re.I | re.S) for m in spec["texte_contient"])
        controles.append((trouve, "brouillon contient l'une de : " + " | ".join(spec["texte_contient"]) + "  (indicatif : à relire)"))
    for motif in spec.get("texte_ne_contient", []):
        controles.append((re.search(motif, brouillon, re.I | re.S) is None, f"brouillon ne contient pas /{motif}/"))
    controles.append((res["planning_identique"], "planning inchangé (hachages identiques)"))
    return controles


def _indente(texte: str, marge: str = "    ") -> str:
    return "\n".join(marge + ligne if ligne else "" for ligne in texte.splitlines())


def afficher_sortie(res: dict) -> None:
    resume, fiche = res["resume"], res["fiche"]
    total = f"{resume['total']:.2f} €" if resume["total"] is not None else "aucun"
    print(f"  Réponse : {resume['type']}   |   Total du devis : {total}   |   Devis joint : {'oui' if res['devis'] else 'non'}")
    chambres = {k: v for k, v in fiche["chambres"].items() if v}
    print(f"  Fiche : arrivée {fiche['arrivee']} → départ {fiche['depart']}, effectif {fiche['effectif']}, chambres {chambres}")
    print(f"          salles {[(s['nom'], s['date']) for s in fiche['salles']]}, {len(fiche['repas'])} repas")
    print(f"          hypothèse {fiche['hypothese']}, champs manquants {fiche['champs_manquants']}")
    if res["devis"]:
        print("  Lignes du devis :")
        print(_indente("\n".join(l for l in res["devis"].splitlines() if l.startswith("|") and not l.startswith("|---"))))
    corps = res["brouillon"].split("\n---\n", 1)[-1].split("\nCordialement,")[0].strip()
    print("  Brouillon (corps du message) :")
    print(_indente(corps))


def afficher_cas(cas: dict, res: dict | None, erreur: str | None) -> bool:
    print("\n" + "=" * LARGEUR)
    print(f"CAS {cas['numero']} – {cas['sujet']}")
    print("=" * LARGEUR)
    print("ENTRÉE")
    print(f"  Cadrage : {cas['entree']}")
    if cas["adaptation"]:
        print(f"  Adaptation à la grille : {cas['adaptation']}")
    print(f"  Courriel soumis à l'agent (objet : {cas['courriel']['sujet']}) :")
    print(_indente(cas["courriel"]["corps"]))
    print("SORTIE")
    if erreur:
        print(f"  ERREUR pendant l'exécution : {erreur}")
    else:
        afficher_sortie(res)
        if cas["calcul_manuel"]:
            print(f"  Calcul manuel de référence : {cas['calcul_manuel']}")
    print("RÉSULTAT ATTENDU")
    print(f"  {cas['resultat_attendu']}")
    controles = [] if erreur else verifier(cas["verifications"], res)
    print("VÉRIFICATIONS")
    for ok, libelle in controles:
        print(f"  {'✔' if ok else '✘'} {libelle}")
    reussi = bool(controles) and all(ok for ok, _ in controles)
    print(f"RÉSULTAT : {'✔ RÉUSSI' if reussi else '✘ ÉCHEC'}")
    return reussi


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    garder = "--garder" in sys.argv
    numeros = {int(a) for a in sys.argv[1:] if a.isdigit()}
    cas_a_lancer = [c for c in json.loads(FICHIER_CAS.read_text(encoding="utf-8"))["cas"]
                    if not numeros or c["numero"] in numeros]

    racine = SORTIE / "cas_de_test" if garder else Path(tempfile.mkdtemp(prefix="cas_de_test_"))
    mails, sortie = racine / "mails", racine / "out"
    mails.mkdir(parents=True, exist_ok=True)
    print(f"Exécution de {len(cas_a_lancer)} cas par l'agent MCP (appels au modèle). Fichiers produits dans : {racine}\n")
    resultats = {}
    try:
        for cas in cas_a_lancer:
            ecrire_courriel(cas, mails)
        avant = empreintes()
        try:
            resumes = {r["id"]: r for r in traiter_boite(ids=[id_cas(c) for c in cas_a_lancer], sortie=sortie, mails=mails)}
        except Exception as e:  # MODEL ou clé absents, serveur MCP injoignable...
            sys.exit(f"Exécution impossible : {type(e).__name__}: {e}")
        identique = empreintes() == avant
        for cas in cas_a_lancer:
            try:
                res, erreur = recueillir(cas, resumes[id_cas(cas)], sortie, identique), None
            except Exception as e:  # un cas en échec ne doit pas empêcher l'affichage des autres
                res, erreur = None, f"{type(e).__name__}: {e}"
            resultats[cas["numero"]] = afficher_cas(cas, res, erreur)
    finally:
        if not garder:
            shutil.rmtree(racine, ignore_errors=True)

    print("\n" + "=" * LARGEUR)
    print("SYNTHÈSE : " + "  ".join(f"cas {n} {'✔' if ok else '✘'}" for n, ok in resultats.items()))
    print(f"{sum(resultats.values())}/{len(resultats)} cas réussis")


if __name__ == "__main__":
    main()
