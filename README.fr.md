<a href="https://lintvoice.com"><picture><source media="(prefers-color-scheme: dark)" srcset="https://lintvoice.com/static/logo/lintvoice-wordmark-dark.svg"><img src="https://lintvoice.com/static/logo/lintvoice-wordmark-light.svg" alt="lintvoice" width="160"></picture></a>

# Vérifiez, comprenez et corrigez vos factures électroniques

[Read in English](README.md)

lintvoice applique les règles officielles à vos factures électroniques : celles de la norme européenne, puis celles de chaque pays, à commencer par la France. Repérez les factures invalides dans votre CI, en une commande, sans Java, sans serveur et sans compte : vos factures ne sont envoyées nulle part.

Chaque règle en échec est nommée, avec son message officiel et, pour les totaux et la TVA, le calcul fait avec les valeurs de votre facture. Sur [lintvoice.com](https://lintvoice.com/fr/regles/), la page d'une règle dit en mots simples ce qu'elle vérifie et comment corriger une facture qui y échoue.

Aujourd'hui, il applique :

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

Pour les règles de totaux et de TVA (BR-CO-10 à 17, BR-S-08 et BR-S-09), lintvoice montre le calcul avec les montants de la facture, par exemple : `1025.00 (BT-109) + 205.00 (BT-110) = 1230.00; the invoice states 1231.00 (BT-112), a gap of 1.00`, et, pour une règle vérifiée taux par taux, le taux en erreur. En JSON, chaque fichier porte aussi les valeurs lues dans la facture (`values`).

Pour une seule règle, `lintvoice check --rule BR-CO-15 facture.pdf` répond pour cette règle : elle échoue, elle ne trouve pas d'erreur, elle ne s'applique pas à la facture (et pourquoi), ou elle n'a pas pu être vérifiée. Les erreurs des autres règles tiennent en une ligne.

Détails (jeux de règles, licences, codes de sortie, limites) : [README.md](README.md).

## Depuis un agent de code

Une skill (au format [Agent Skills](https://agentskills.io)) indique à un agent de code quand lancer lintvoice,
comment lire le résultat et où chaque règle est expliquée.

- Claude Code : `claude plugin marketplace add lintvoice/lintvoice`, puis `claude plugin install lintvoice@lintvoice`.
  Pour recevoir les mises à jour, activez la mise à jour automatique de la marketplace dans `/plugin`, rubrique
  Marketplaces.
- Autres agents (Codex, Cursor, GitHub Copilot, Gemini CLI…) : `npx skills add lintvoice/lintvoice` ;
  `npx skills update` installe la dernière version.
