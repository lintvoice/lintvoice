# lintvoice vérifie vos factures électroniques au regard des règles et normes officielles

[Read in English](README.md)

Il commence par la norme européenne, puis ajoute les règles propres à chaque pays. Il fonctionne **hors ligne** : vos factures ne sont envoyées nulle part. Aujourd'hui, il applique :

- **EN 16931**, la norme européenne, pour CII et UBL ;
- les règles de profil **Factur-X 1.09.2**, pour les PDF Factur-X ;
- **BR-FR**, les règles de la réforme française publiées par le FNFE-MPE (France_RFE), quand le vendeur est en France.

Les résultats sont regroupés par règle (par exemple, un numéro de TVA manquant apparaît une fois, et non pour chaque ligne de facture en erreur).

## Démarrage

```sh
uvx lintvoice rules install      # une fois : télécharge les jeux de règles, à version figée
uvx lintvoice check facture.pdf
uvx lintvoice check factures/ --format json
```

Ou `pip install lintvoice` (Python 3.10 ou plus). Chaque version est aussi publiée sur [GitHub Releases](https://github.com/lintvoice/lintvoice/releases) (wheel et sdist), si PyPI est inaccessible.

`lintvoice rules install` télécharge les règles officielles depuis leurs sources, en https, et vérifie leur empreinte. Les dossiers de France_RFE qui contiennent des documents AFNOR ne sont jamais extraits. Après cette installation, toutes les vérifications se font sans réseau. Les règles BR-FR s'appliquent quand le pays du vendeur (BT-40) est FR ; `--rules en16931,factur-x,br-fr` les impose.

Détails (jeux de règles, licences, codes de sortie, limites) : [README.md](README.md).
