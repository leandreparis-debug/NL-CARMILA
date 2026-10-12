-- Rubrique 6 : libellé facultatif du lien vers les plans de développement
-- (NULL = libellé par défaut « Voir les plans de développement »).
ALTER TABLE newsletters ADD COLUMN development_plans_label TEXT
    CHECK (development_plans_label IS NULL OR length(development_plans_label) <= 100);
