# VintedScrap 🛍️

> Application de bureau Python pour rechercher, filtrer et surveiller les annonces Vinted — avec interface graphique moderne dark mode.

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![CustomTkinter](https://img.shields.io/badge/UI-CustomTkinter-teal)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey?logo=windows)
![License](https://img.shields.io/badge/License-MIT-green)

---

## ✨ Fonctionnalités

### 🔍 Recherche
- Recherche par mots-clés sur l'API publique Vinted France
- **Multi-termes** : plusieurs recherches en une seule fois, séparées par une virgule (`op12 display, luffy sr`)
- **Filtrage strict** : tous les mots doivent être présents dans le titre (zéro résultat hors-sujet)
- Normalisation : `OP-12`, `Op 12` et `op12` sont traités identiquement
- **Pagination automatique** : jusqu'à ~480 annonces par recherche
- Filtre par prix min / max et par état (Neuf, Très bon état, Bon état, Satisfaisant)
- Tri dynamique par prix croissant / décroissant sans relancer la recherche
- **Recommandations au démarrage** basées sur l'historique de recherche

### 🃏 Affichage
- Grille de cartes adaptive (2 à 4 colonnes selon la taille de la fenêtre)
- Image, titre, prix, marque, état et badge **✦ NOUVEAU** sur chaque carte
- **Mode liste** en plus du mode grille
- **Aperçu rapide** : clic sur une image → popup avec photo HD, description complète, lien Vinted
- Clic droit sur une image → Copier l'image / Enregistrer / Copier le lien
- Chargement progressif des images (pas de freeze)

### 🔔 Alertes automatiques
- Relance la recherche toutes les **5 / 10 / 15 / 30 minutes** en arrière-plan
- Notification Windows native + bannière visuelle si de nouvelles annonces apparaissent
- Affichage du prochain check dans la sidebar

### ⭐ Favoris
- Bouton ♥ sur chaque carte pour épingler une annonce
- Persistant entre les sessions (`data/favoris.json`)
- Onglet dédié dans la sidebar avec suppression rapide

### 📋 Recherches sauvegardées
- Sauvegarde une recherche complète (mots-clés + filtres prix) sous un nom personnalisé
- Rechargement en un clic depuis l'onglet dédié

### 📊 Historique des prix
- Enregistre le prix de chaque annonce à chaque recherche
- Bouton 📈 sur chaque carte → graphique d'évolution du prix dans le temps

### 🎯 File de ciblage
- Ajouter des annonces à une file de négociation
- Score de négociabilité (0–100), prix suggéré et message prêt à copier-coller
- Export CSV de la file de ciblage

### 📈 Dashboard statistiques
- Répartition des prix, marques les plus présentes, états, vendeurs récurrents
- Graphiques générés depuis les résultats de recherche

### 👤 Connexion compte (optionnelle)
- Connexion compte Vinted optionnelle, en lecture seule
- Credentials chiffrés localement (XOR + base64)
- L'application fonctionne entièrement sans compte

---

## 📁 Structure du projet

```
VintedScrapV2/
├── main.py                    ← Interface graphique (CustomTkinter)
├── core/
│   ├── scraper.py             ← Requêtes API Vinted + parsing
│   ├── data.py                ← Persistance JSON (favoris, recherches, historique)
│   ├── analyzer.py            ← Analyse de prix et score de négociation
│   ├── comparateur_prix.py    ← Comparateur d'annonces côte à côte
│   ├── recommandations.py     ← Recommandations basées sur l'historique
│   └── auth.py                ← Connexion compte Vinted (optionnelle)
├── data/
│   ├── favoris.json           ← Annonces favorites (généré à l'usage)
│   ├── recherches.json        ← Recherches sauvegardées (généré à l'usage)
│   ├── historique.json        ← Historique des prix (généré à l'usage)
│   ├── historique_recherches.json ← Termes recherchés (généré à l'usage)
│   └── cibles.json            ← File de ciblage (généré à l'usage)
├── requirements.txt
├── installer.bat              ← Installation automatique des dépendances
├── lancer.bat                 ← Lancer l'application
└── PATCHNOTE.md
```

> Les fichiers dans `data/` sont générés automatiquement. Ils sont ignorés par Git.

---

## 🚀 Installation

### Prérequis
- **Python 3.10 ou supérieur** → [python.org/downloads](https://www.python.org/downloads/)
- Cocher **"Add Python to PATH"** lors de l'installation
- **Windows uniquement** (notifications natives Windows, presse-papier image)

### 1. Cloner le dépôt
```bash
git clone https://github.com/TON_PSEUDO/VintedScrapV2.git
cd VintedScrapV2
```

### 2. Installer les dépendances
Double-clic sur **`installer.bat`**

ou en ligne de commande :
```bash
pip install -r requirements.txt
```

### 3. Lancer l'application
Double-clic sur **`lancer.bat`**

ou en ligne de commande :
```bash
python main.py
```

---

## 🎮 Utilisation rapide

| Action | Comment |
|--------|---------|
| Recherche simple | Saisir un mot-clé → Entrée ou bouton Rechercher |
| Multi-recherche | Séparer par virgules : `op12, luffy sr, nike dunk` |
| Aperçu d'un article | Cliquer sur l'image de la carte |
| Copier une image | Clic droit sur l'image → Copier l'image |
| Mettre en favori | Bouton ♥ sur la carte |
| Sauvegarder une recherche | Bouton 💾 dans la sidebar → donner un nom |
| Voir l'historique des prix | Bouton 📈 sur une carte |
| Activer les alertes | Sidebar → section Alerte → choisir l'intervalle |
| Ajouter à la file de ciblage | Bouton 🎯 sur une carte |
| Exporter en CSV | Bouton Export dans la barre du haut |

---

## 📦 Dépendances

| Bibliothèque | Version | Usage |
|---|---|---|
| `customtkinter` | ≥ 5.2.0 | Interface graphique dark mode |
| `requests` | ≥ 2.31.0 | Requêtes API Vinted |
| `Pillow` | ≥ 10.0.0 | Chargement et affichage des images |
| `pywin32` | ≥ 306 | Copie image dans le presse-papier Windows |
| `windows-toasts` | ≥ 1.0.0 | Notifications Windows natives |

---

## ⚠️ Avertissements

- Ce projet utilise l'**API publique non-officielle** de Vinted France. Il peut cesser de fonctionner si Vinted modifie son API.
- Aucun compte Vinted n'est nécessaire pour utiliser l'application.
- Ce projet est à des fins **éducatives et personnelles** uniquement. Respectez les conditions d'utilisation de Vinted.
- Ne pas utiliser de manière intensive ou automatisée.

---

## 📋 Changelog

Voir [PATCHNOTE.md](PATCHNOTE.md) pour le détail des versions.

---

## 📄 Licence

MIT — libre d'utilisation, de modification et de distribution.
