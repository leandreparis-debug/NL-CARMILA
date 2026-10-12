-- Ajout manuel d'un article dont le site refuse la lecture automatique (403, protection
-- anti-robot) : l'utilisateur confirme avoir ouvert le lien dans son navigateur.
-- 1 = « lien vérifié par l'utilisateur » (affiché sur la carte de l'article).
ALTER TABLE articles ADD COLUMN link_verified_by_user INTEGER NOT NULL DEFAULT 0
    CHECK (link_verified_by_user IN (0, 1));
