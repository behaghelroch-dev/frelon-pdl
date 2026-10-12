# Décisions d'architecture (ADR)

Chaque ADR (*Architecture Decision Record*) décrit une décision structurante : le contexte, la décision
prise, les alternatives écartées et les conséquences assumées.

| N° | Décision | Statut |
|---|---|---|
| [ADR-001](ADR-001-source-gbif.md) | Collecter les observations via l'API GBIF plutôt que via les exports de la plateforme Frelon / INPN | Acceptée |
| [ADR-002](ADR-002-stockage-csv-sqlite.md) | Stocker le curated en CSV + SQLite (fichiers locaux) plutôt que dans une base serveur | Acceptée |
| [ADR-003](ADR-003-cle-metier-et-historisation.md) | Clé métier spatio-temporelle, UPSERT et suppression logique plutôt qu'un snapshot écrasé | Acceptée |
