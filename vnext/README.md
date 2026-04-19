# VintedScrap Next

Base propre pour une future version publiable sur GitHub.

## Objectifs

- séparer le domaine, les services, la persistance et l'UI
- éviter les secrets et données utilisateur dans le dépôt
- rendre la logique testable sans lancer l'interface
- préparer une vraie montée en qualité avant publication

## Structure

```text
vnext/
├── pyproject.toml
├── README.md
├── src/
│   └── vintedscrap_vnext/
│       ├── __init__.py
│       ├── __main__.py
│       ├── app.py
│       ├── config.py
│       ├── models.py
│       ├── profile_service.py
│       ├── relevance.py
│       └── repositories.py
└── tests/
    └── test_relevance.py
```

## Ce que cette base apporte déjà

- modèles métier typés
- service de profil utilisateur local
- moteur de scoring explicable
- repository JSON minimal
- shell UI `CustomTkinter` pour repartir proprement
- tests unitaires sur le scoring

## Lancement

Depuis `vnext/`:

```bash
pip install -e .[dev]
python -m vintedscrap_vnext
```

## Étapes suivantes

1. brancher un scraper isolé dans `repositories` / `services`
2. déplacer progressivement les règles métier de `main.py`
3. recréer l'UI écran par écran
4. ajouter tests métier puis tests d'intégration
