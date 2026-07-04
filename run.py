"""Point d'entrée local : `python run.py` (serveur de développement)."""
import os

# En local (HTTP), les cookies « Secure » ne seraient pas transmis : on les
# désactive avant de charger la config pour permettre la connexion.
os.environ.setdefault("ASTRANOTE_COOKIE_SECURE", "0")

from astranote import create_app  # noqa: E402

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
