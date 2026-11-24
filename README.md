# Transformer (v3.3.0)

**Des données propres, vérifiées et prêtes à livrer dans QGIS 3.40 à 4.x (Qt 5 / Qt 6), sans jamais modifier votre fichier d'origine.**

Que vous soyez **non-spécialiste** (chargé d'études, gestionnaire de données, opérateur terrain) ou **géomaticien expérimenté**, **Transformer** vous permet de nettoyer des colonnes, filtrer des lignes, adapter des géométries, comparer visuellement **Avant / Après** et livrer un fichier fiable (GeoPackage, Excel, CSV, GeoJSON, Shapefile, MapInfo, DXF, KML) ou publier dans **PostgreSQL / PostGIS**.

Un **Guide & Tutoriel interactif illustré** (`docs/guide_utilisateur.html`) est directement intégré au plugin : cliquez sur le bouton **Guide & Tuto** (raccourci `F1`) pour l'ouvrir dans un panneau latéral (dock) de QGIS.

---

## 1. Comprendre Transformer en 30 secondes

Modifier directement un fichier reçu comporte deux risques : écraser par erreur une donnée d'origine, et devoir recommencer les mêmes manipulations à chaque nouvelle livraison.

Dans **Transformer** :
1. **Votre fichier de départ reste 100 % intact** : le plugin travaille toujours en copie.
2. **Aucune formule obligatoire** : les outils guidés (*Nettoyer texte*, *Filtrer lignes*, *Géométrie*) préparent vos règles en français courant, tandis que les experts gardent un accès complet aux expressions natives de QGIS.
3. **Vous voyez ce qui change avant de créer le fichier** : l'onglet **Comparer** affiche côte à côte la valeur **Avant** et la valeur **Après** avec un repère visuel sur chaque valeur modifiée.
4. **Vous pouvez enregistrer votre préparation (Recette)** pour la rejouer en un clic sur vos prochains fichiers.

---

## 2. Tutoriel pas à pas (sans aucune formule)

### Étape 1 : Choisir vos données
À l'ouverture de Transformer, la couche active de votre projet QGIS est automatiquement sélectionnée dans le panneau gauche **Mes données**.
- Si votre fichier n'est pas encore ouvert dans QGIS, cliquez sur **Ajouter des données…** (en haut à gauche ou dans le bandeau d'accès rapide) et sélectionnez votre fichier (`.gpkg`, `.shp`, `.geojson`, `.csv`, `.tab`).

### Étape 2 : Nettoyer ou choisir vos colonnes (onglet `Colonnes`)
- **Pour nettoyer un texte en 2 clics** : cliquez sur **Nettoyer texte** dans le bandeau supérieur **Accès rapide**. Choisissez la **Colonne**, puis le **Changement** souhaité :
  - *Retirer les espaces autour* (`"  Saint-Éloi  "` devient `"Saint-Éloi"`) ;
  - *Mettre en majuscules* ou *Mettre en minuscules* ;
  - *Compléter les textes vides* (remplace les cases vides `NULL` ou composées d'espaces par la mention de votre choix, par exemple `Non renseigné`).
  Cliquez sur **Appliquer à cette colonne**.
- **Pour retirer une colonne inutile** : sélectionnez-la dans le tableau **Colonnes du résultat** puis cliquez sur **Exclure** (votre fichier source n'est pas touché).
- **Pour renommer une colonne ou fixer son type** (Texte, Entier, Décimal, Date, Booléen) : double-cliquez sur la ligne ou appuyez sur `F2` (**Définir…**).

### Étape 3 : Garder uniquement les lignes utiles (onglet `Lignes`)
Cliquez sur **Filtrer lignes** (ou sur l'onglet **Lignes**) :
1. Choisissez la colonne dans *Garder les lignes dont* ;
2. Choisissez la condition (*est égal à*, *contient le texte*, *n'est pas renseigné*, *est supérieur à*) ;
3. Saisissez la valeur recherchée et cliquez sur **Appliquer cette condition**.

### Étape 4 : Adapter la forme ou les coordonnées (onglet `Géométrie`, facultatif)
Si votre couche contient des formes géographiques (points, lignes, polygones) :
- Vous pouvez conserver la forme d'origine, **représenter chaque objet par un point** (centroïde), ou **créer une zone autour de chaque objet** (zone tampon en mètres).
- Vous pouvez également choisir un **SCR de sortie** (par exemple convertir du Lambert-93 `EPSG:2154` vers le GPS `EPSG:4326`).
- *Note : si votre entrée est un simple tableau sans carte (CSV), cet onglet se désactive automatiquement.*

### Étape 5 : Vérifier l'Avant / Après (onglet `Comparer`)
Cliquez sur le bouton principal **Comparer les changements** (en bas à droite ou dans la barre d'outils) :
- Le tableau **Comparer** lit un échantillon (jusqu'à 50 lignes) et affiche côte à côte `Avant · colonne` et `Après · colonne`.
- Chaque valeur modifiée est signalée par une icône et un fond distincts.

### Étape 6 : Créer le résultat puis livrer le fichier (onglet `Livrer`)
1. Une fois la comparaison vérifiée, cliquez sur **Créer le résultat** (`F6`) : la couche préparée est créée.
2. Cliquez sur **Choisir comment livrer** (ou sur l'onglet supérieur **Livrer**).
3. Choisissez le **Format du fichier** :
   - **GeoPackage (`.gpkg`, recommandé)** : un seul fichier moderne pour les colonnes et les géométries, sans troncature des noms de colonnes ;
   - **GeoJSON (`.geojson`)** : échange web et interopérabilité ;
   - **Classeur Excel (`.xlsx`) / CSV (`.csv`)** : tableaux de valeurs sans géométrie ;
   - **Shapefile (`.shp`) / MapInfo (`.tab`) / DXF (`.dxf`) / KML (`.kml`) / GML / SQLite / FlatGeobuf**.
4. Choisissez l'emplacement avec **Parcourir…** puis cliquez sur **Créer le fichier**.
5. Une fois l'écriture confirmée, cliquez sur **Ouvrir dans QGIS** si vous souhaitez ajouter le fichier livré à votre carte.

---

## 3. Réutiliser votre travail sur un prochain fichier (Recettes)

Vous n'avez pas besoin de refaire ces réglages la semaine suivante :
1. Donnez un nom explicite dans le champ **Préparation** puis cliquez sur **Enregistrer la préparation** (`Ctrl+S`).
2. Lorsqu'un nouveau fichier arrive, sélectionnez votre préparation dans **Mes données** à gauche et cliquez sur **Changer de données…** (ou clic droit > **Relier une livraison…**).
3. Choisissez la nouvelle couche : Transformer vérifie la compatibilité des colonnes et applique toute votre préparation immédiatement.
4. Pour transmettre vos préparations à un collègue : **Outils > Exporter les recettes…** (`.json`), puis **Importer…** (`Ctrl+O`).

---

## 4. Fonctions avancées pour les géomaticiens

### Expressions QGIS natives
En activant **Expression avancée** dans l'onglet **Colonnes**, vous éditez directement les formules QGIS sur la même préparation que le mode guidé :

```qgis
upper(trim("code_ouvrage"))
concat("commune", ' - ', "numero")
coalesce("observation", 'Non renseigné')
round(area($geometry), 2)
centroid($geometry)
buffer($geometry, 25)
```

### Garanties d'intégrité des données et géométries
- **Ordre géométrique strict** : l'expression géométrique est évaluée dans le SCR source avant reprojection vers le SCR cible. Un tampon (`buffer`) sur un SCR géographique en degrés est bloqué avant exécution.
- **Précontrôle d'export fichier** : avant toute écriture Shapefile/DBF ou MapInfo TAB, le moteur vérifie la longueur en octets dans l'encodage choisi, les collisions de noms à 10 octets et les dépassements numériques. Aucune donnée n'est tronquée en silence.
- **Filtres protégés** : un filtre actif invalide ou référençant une colonne absente bloque l'exécution au lieu d'exporter silencieusement toutes les lignes.
- **Publication PostgreSQL / PostGIS sécurisée** :
  - L'analyse préalable est strictement non destructive (aucune table créée, modifiée ou supprimée avant votre confirmation).
  - En mode **Remplacer les données**, le `DELETE` et l'`INSERT` partagent la même transaction SQL par table (rollback complet en cas d'erreur ou d'annulation).
  - Les identifiants utilisent le coffre d'authentification QGIS (`authcfg`) : aucun mot de passe n'est stocké en clair dans les recettes, profils, journaux ou diagnostics.

---

## 5. Repères de l'interface et raccourcis

| Élément / Raccourci | Action |
| --- | --- |
| **Guide & Tuto (`F1`)** | Ouvrir la documentation interactive illustrée dans un dock latéral QGIS |
| **Nouvelle (`Ctrl+N`)** | Réinitialiser un brouillon sur la couche courante |
| **Importer… (`Ctrl+O`)** | Importer une bibliothèque de préparations JSON |
| **Enregistrer (`Ctrl+S`)** | Enregistrer la préparation courante |
| **Comparer** | Calculer l'aperçu Avant / Après sur 50 objets sans modifier la source |
| **Créer le résultat (`F6`)** | Exécuter la transformation complète en tâche de fond |
| **Double-clic / `F2` / `Suppr`** | Sur une colonne de la matrice : définir son nom/type (`F2`) ou l'exclure (`Suppr`) |

---

## 6. Fournisseur QGIS Processing et API Python headless (v3.3.0)

- **Fournisseur Processing natif** (`hasProcessingProvider=yes`) compatible Modeleur graphique, traitements par lots et `qgis_process` :
  - `transformer:apply_recipe` : rejouer une recette JSON portable ou locale avec surcharges optionnelles (filtre, géométrie, SCR) et précontrôle strict du schéma.
  - `transformer:transform_vector` : transformation vectorielle ad-hoc (correspondance et expressions de champs, filtre strict, géométrie avant reprojection, SCR cible).
  - `transformer:publish_postgresql` : publication transactionnelle vers PostgreSQL / PostGIS (`append`, `replace`, `update`) via connexions QGIS (`authcfg`).
- **API Python headless (`Transfomer.api`)** : `list_recipes`, `load_recipe`, `export_recipe`, `apply_recipe`, `transform_vector`, `publish_postgresql`.

---

## 7. Installation et prérequis

- **QGIS** : de QGIS 3.40 LTR (Qt 5) jusqu'aux dernières versions QGIS 4.x (Qt 6), vérifié sous QGIS 3.40.15 / Qt 5.15 et QGIS 4.2.1 / Qt 6.11.
- **Installation** : depuis le dépôt officiel QGIS (`Plugins > Manage and Install Plugins > Transformer`) ou depuis le ZIP (`Transfomer.zip`).

---

## 8. Auteur et licence

- **Auteur** : Youcef ADDA | GEODECI | [https://geodeci.xyz/](https://geodeci.xyz/) | [youcef.geodesien@gmail.com](mailto:youcef.geodesien@gmail.com)
- **Dépôt et tickets** : [github.com/yadda07/Transformer](https://github.com/yadda07/Transformer) · [Issues](https://github.com/yadda07/Transformer/issues)
- **Licence** : MIT (`LICENSE`)
