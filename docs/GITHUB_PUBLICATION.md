# Publication GitHub

## Avant publication

- Revoquer tous les webhooks, tokens et identifiants deja utilises localement.
- Verifier que `data/` et `data/cache/` ne sont plus suivis par Git.
- Nettoyer les fichiers avec problemes d'encodage avant la release publique.
- Garder les exemples de configuration separes des vraies donnees locales.

## Ce qui est maintenant isole

- Profil utilisateur local : `data/user_profile.json`
- Evenements utilisateur : `data/user_events.json`
- Cache descriptions / recherches : `data/cache/`
- Historique revente : `data/resell_history.json`

## Checklist recommandee

1. Creer un `README` public oriente installation et cas d'usage.
2. Ajouter un `requirements.txt` ou `pyproject.toml` final de distribution.
3. Lancer `python -m py_compile main.py core\\*.py` avant chaque tag.
4. Retirer les donnees personnelles du depot avant `git push`.
5. Publier une capture d'ecran propre de l'interface.
