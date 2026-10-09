-- Détection des opportunités et des franchisés (étape 5).
-- Chaque détection garde sa preuve : la phrase source (texte brut, ≤ 400 caractères)
-- et les termes déclencheurs (liste JSON). Le travail de l'utilisateur est protégé :
-- opportunity_source = 'manual' (repère modifié à la main), franchisees.edited (fiche
-- modifiée à la main), franchisees.dismissed (suggestion écartée), validated.

ALTER TABLE articles ADD COLUMN opportunity_source TEXT
    CHECK (opportunity_source IS NULL OR opportunity_source IN ('auto', 'manual'));
ALTER TABLE articles ADD COLUMN opportunity_evidence TEXT
    CHECK (opportunity_evidence IS NULL OR length(opportunity_evidence) <= 400);
ALTER TABLE articles ADD COLUMN opportunity_terms TEXT NOT NULL DEFAULT '[]'
    CHECK (json_valid(opportunity_terms));

-- confidence NULL : fiche saisie à la main (jamais touchée par la détection).
ALTER TABLE franchisees ADD COLUMN confidence TEXT
    CHECK (confidence IS NULL OR confidence IN ('haute', 'moyenne', 'basse'));
ALTER TABLE franchisees ADD COLUMN evidence TEXT
    CHECK (evidence IS NULL OR length(evidence) <= 400);
ALTER TABLE franchisees ADD COLUMN trigger_terms TEXT NOT NULL DEFAULT '[]'
    CHECK (json_valid(trigger_terms));
ALTER TABLE franchisees ADD COLUMN edited INTEGER NOT NULL DEFAULT 0
    CHECK (edited IN (0, 1));
ALTER TABLE franchisees ADD COLUMN dismissed INTEGER NOT NULL DEFAULT 0
    CHECK (dismissed IN (0, 1));

CREATE INDEX idx_articles_opportunity ON articles (newsletter_id, is_opportunity);
