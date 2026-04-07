# 📋 VintedScrap — Patchnotes

---

## v3.1.0 — 2025-04-03

### 🐛 Corrections de bugs

#### Connexion compte Vinted (Erreur 404)
- L'endpoint `/api/v2/sessions` utilisé pour le login n'est plus disponible sur Vinted.
- Le système de connexion essaie maintenant **3 endpoints dans l'ordre** :
  1. `/api/v2/users/login` ← prioritaire
  2. `/api/v2/sessions` ← fallback (ancien)
  3. `/oauth/token` ← fallback OAuth
- Si tous les endpoints échouent (404), un message clair est affiché :
  *"L'API de connexion Vinted est inaccessible. L'application fonctionne sans compte — la connexion est optionnelle."*
- La structure de réponse JSON est désormais gérée de façon plus souple
  (variations `user`, `data.user`, ou objet direct selon l'endpoint).

#### Interface — Onglets tronqués dans la sidebar
- Les 5 onglets de la sidebar ne tenaient pas dans la largeur de 300px
  et leurs labels étaient coupés.
- Labels raccourcis pour tenir en toute circonstance :
  - `"🔍 Recherche"` → `"🔍 Rech."`
  - `"⭐ Favoris"` → `"⭐ Favs"`
  - `"📋 Sauveg."` → `"📋 Sauv."`
  - `"👤 Compte"` → inchangé
  - `"🎯 Ciblage"` → `"🎯 Cibles"`

### 🎨 Améliorations UI

- **Sidebar élargie** : 300px → 320px pour plus de confort de lecture.
- **Fenêtre principale** : taille par défaut ajustée (1340×880 → 1380×880)
  et taille minimale augmentée (1000×660 → 1040×660) en conséquence.
- **Message d'erreur login** : le `wraplength` du label d'erreur sous
  le bouton "Se connecter" est passé de 240px à 280px — les messages
  longs (ex. erreur 404 explicative) s'affichent maintenant en entier
  sans être coupés.

---

## v3.0.0 — version initiale

- Interface graphique CustomTkinter dark mode
- Recherche avancée multi-termes sur l'API Vinted (23 pays)
- Filtres : prix, état, catégorie, couleur, vendeur
- Affichage grille / liste avec chargement progressif des images
- Favoris persistants (`favoris.json`)
- Recherches sauvegardées (`recherches.json`)
- Historique des prix par annonce avec graphique (`historique.json`)
- Alertes automatiques (5 / 10 / 15 / 30 min) + notifications Windows
- Comparateur d'annonces (jusqu'à 3 articles côte à côte)
- Dashboard statistiques (marques, états, vendeurs, répartition des prix)
- Analyse de prix & score de négociabilité (0–100)
- File de ciblage avec message prêt à copier-coller
- Export CSV
- Connexion compte Vinted optionnelle (lecture seule)
- Chiffrement local des credentials (XOR + base64)
