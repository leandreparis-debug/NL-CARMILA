-- Texte brut de l'article (tronqué à 20 000 caractères), récupéré par le collecteur.
-- Sert à la détection des franchisés et des opportunités ; jamais affiché tel quel.
ALTER TABLE articles ADD COLUMN body_text TEXT
    CHECK (body_text IS NULL OR length(body_text) <= 20000);
