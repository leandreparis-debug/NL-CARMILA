-- Enseigne saisie librement dans l'interface de relecture (choix « Autre »), pour un
-- article qui ne concerne pas l'une des enseignes suivies (brands).
ALTER TABLE articles ADD COLUMN brand_label TEXT
    CHECK (brand_label IS NULL OR length(brand_label) <= 100);
