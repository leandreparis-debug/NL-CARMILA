-- Rubrique 6 : jusqu'à 6 liens vers les plans de développement (un par région), chacun
-- avec son libellé (NULL = « Voir les plans de développement »). Remplace les colonnes
-- newsletters.development_plans_url / development_plans_label, reprises ici en lien n° 1
-- puis vidées (les colonnes restent, inutilisées : SQLite ne les supprime pas simplement).
CREATE TABLE development_plan_links (
    id            INTEGER PRIMARY KEY,
    newsletter_id INTEGER NOT NULL REFERENCES newsletters (id) ON DELETE CASCADE,
    position      INTEGER NOT NULL CHECK (position BETWEEN 1 AND 6),
    label         TEXT CHECK (label IS NULL OR length(label) <= 100),
    url           TEXT NOT NULL
                  CHECK (url LIKE 'http://_%' OR url LIKE 'https://_%'),
    UNIQUE (newsletter_id, position)
);

INSERT INTO development_plan_links (newsletter_id, position, label, url)
    SELECT id, 1, development_plans_label, development_plans_url
    FROM newsletters
    WHERE development_plans_url IS NOT NULL;

UPDATE newsletters SET development_plans_url = NULL, development_plans_label = NULL;
