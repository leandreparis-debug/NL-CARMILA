-- Détection sensible à la majuscule initiale pour les enseignes dont le nom est aussi
-- un mot courant (ex. « Adopt » ne doit pas correspondre à « adopter »).
ALTER TABLE brands ADD COLUMN case_sensitive INTEGER NOT NULL DEFAULT 0
    CHECK (case_sensitive IN (0, 1));
