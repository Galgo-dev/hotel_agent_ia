"""Page web locale de relecture : le service commercial valide ou rejette chaque brouillon (aucun envoi)."""
import secrets
import webbrowser
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from src.brouillons import SORTIE, TITRES
from src.revision import enregistrer_decision, lister_brouillons

STATUTS = {None: "en attente", "valide": "validé", "rejete": "rejeté"}
STYLE = """body{font-family:system-ui,sans-serif;max-width:60rem;margin:0 auto;padding:1rem;background:#f4f4f2;color:#222}
.carte{background:#fff;border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}
.carte.valide{border-left:6px solid #2e7d32}.carte.rejete{border-left:6px solid #c62828}.carte.attente{border-left:6px solid #999}
pre{white-space:pre-wrap;background:#fafafa;padding:.75rem;border-radius:6px;font-family:inherit}
button{padding:.5rem 1rem;border:0;border-radius:6px;color:#fff;cursor:pointer;margin-right:.5rem}
.ok{background:#2e7d32}.ko{background:#c62828}.statut{float:right;font-weight:600}"""


def _carte(b: dict, token: str) -> str:
    classe = b["decision"] or "attente"
    devis = f"<details><summary>Devis joint</summary><pre>{escape(b['devis'])}</pre></details>" if b["devis"] else ""
    boutons = "".join(
        f'<button class="{css}" name="decision" value="{valeur}">{libelle}</button>'
        for valeur, libelle, css in (("valide", "Valider", "ok"), ("rejete", "Rejeter", "ko")))
    return (f'<section class="carte {classe}"><span class="statut">{STATUTS[b["decision"]]}</span>'
            f'<h2>{escape(b["id"])} – {escape(TITRES.get(b["type"], b["type"]))}</h2>'
            f'<pre>{escape(b["contenu"])}</pre>{devis}'
            f'<form method="post" action="/decision"><input type="hidden" name="token" value="{token}">'
            f'<input type="hidden" name="id" value="{escape(b["id"])}">{boutons}</form></section>')


def page(brouillons: list[dict], token: str) -> str:
    """Construit la page HTML ; tout texte issu des brouillons est échappé."""
    compte = {k: sum(b["decision"] == k for b in brouillons) for k in (None, "valide", "rejete")}
    resume = f"{compte['valide']} validé(s), {compte['rejete']} rejeté(s), {compte[None]} en attente"
    cartes = "".join(_carte(b, token) for b in brouillons) or "<p>Aucun brouillon : lancez d'abord python main.py.</p>"
    return (f'<!doctype html><html lang="fr"><head><meta charset="utf-8"><title>Relecture des brouillons</title>'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><style>{STYLE}</style></head><body>'
            f"<h1>Relecture des brouillons – Le Grand Cèdre</h1><p>{resume}. Valider ne déclenche aucun envoi : "
            f"le brouillon est copié dans out/valides/.</p>{cartes}</body></html>")


def creer_serveur(sortie: Path = SORTIE, port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Crée le serveur local (127.0.0.1 uniquement) et le jeton qui protège les décisions."""
    token = secrets.token_urlsafe(16)

    class Gestionnaire(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/":
                return self.send_error(404)
            corps = page(lister_brouillons(sortie), token).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

        def do_POST(self):
            if self.path != "/decision":
                return self.send_error(404)
            champs = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8"))
            if champs.get("token") != [token]:
                return self.send_error(403)
            try:
                enregistrer_decision(champs.get("id", [""])[0], champs.get("decision", [""])[0], sortie)
            except ValueError:
                return self.send_error(400)
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Gestionnaire), token


def lancer(sortie: Path = SORTIE, port: int = 8765) -> None:
    """Ouvre la page de relecture dans le navigateur ; Ctrl+C pour arrêter."""
    serveur, _ = creer_serveur(sortie, port)
    url = f"http://127.0.0.1:{serveur.server_port}/"
    print(f"Relecture des brouillons : {url}  (Ctrl+C pour arrêter)")
    webbrowser.open(url)
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        serveur.server_close()
