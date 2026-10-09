-- Schéma initial de News Franchise.
-- Dates en ISO 8601 (texte) ; mois de newsletter au format AAAA-MM.
-- Règle du projet : aucun lien inventé. Toute URL stockée commence par http:// ou https://.

CREATE TABLE newsletters (
    id                    INTEGER PRIMARY KEY,
    month                 TEXT NOT NULL UNIQUE
                          CHECK (month GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'
                                 AND CAST(substr(month, 6, 2) AS INTEGER) BETWEEN 1 AND 12),
    status                TEXT NOT NULL DEFAULT 'draft'
                          CHECK (status IN ('draft', 'reviewed', 'exported')),
    development_plans_url TEXT
                          CHECK (development_plans_url IS NULL
                                 OR development_plans_url LIKE 'http://_%'
                                 OR development_plans_url LIKE 'https://_%'),
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

CREATE TABLE brands (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE CHECK (trim(name) <> ''),
    slug    TEXT NOT NULL UNIQUE CHECK (trim(slug) <> ''),
    sector  TEXT NOT NULL DEFAULT '',
    aliases TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(aliases)),
    tracked INTEGER NOT NULL DEFAULT 1 CHECK (tracked IN (0, 1))
);

CREATE TABLE articles (
    id             INTEGER PRIMARY KEY,
    newsletter_id  INTEGER NOT NULL REFERENCES newsletters (id) ON DELETE CASCADE,
    rubric         INTEGER NOT NULL CHECK (rubric IN (1, 2)),
    brand_id       INTEGER REFERENCES brands (id),
    sector         TEXT,
    title          TEXT NOT NULL CHECK (trim(title) <> ''),
    published_at   TEXT,
    source_name    TEXT NOT NULL CHECK (trim(source_name) <> ''),
    url            TEXT NOT NULL CHECK (url LIKE 'http://_%' OR url LIKE 'https://_%'),
    excerpt        TEXT,
    is_opportunity INTEGER NOT NULL DEFAULT 0 CHECK (is_opportunity IN (0, 1)),
    selected       INTEGER NOT NULL DEFAULT 1 CHECK (selected IN (0, 1)),
    position       INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    collected_at   TEXT NOT NULL,
    UNIQUE (newsletter_id, url)
);

CREATE TABLE franchisees (
    id            INTEGER PRIMARY KEY,
    newsletter_id INTEGER NOT NULL REFERENCES newsletters (id) ON DELETE CASCADE,
    name          TEXT NOT NULL CHECK (trim(name) <> ''),
    brands        TEXT NOT NULL DEFAULT '',
    location      TEXT,
    store_count   INTEGER CHECK (store_count IS NULL OR store_count >= 0),
    source_name   TEXT NOT NULL CHECK (trim(source_name) <> ''),
    source_url    TEXT NOT NULL
                  CHECK (source_url LIKE 'http://_%' OR source_url LIKE 'https://_%'),
    article_id    INTEGER REFERENCES articles (id) ON DELETE SET NULL,
    validated     INTEGER NOT NULL DEFAULT 0 CHECK (validated IN (0, 1)),
    position      INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0)
);

CREATE TABLE openings (
    id            INTEGER PRIMARY KEY,
    newsletter_id INTEGER NOT NULL REFERENCES newsletters (id) ON DELETE CASCADE,
    brand_name    TEXT NOT NULL CHECK (trim(brand_name) <> ''),
    location      TEXT NOT NULL CHECK (trim(location) <> ''),
    opening_date  TEXT,
    description   TEXT,
    position      INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0)
);

CREATE TABLE opening_photos (
    id         INTEGER PRIMARY KEY,
    opening_id INTEGER NOT NULL REFERENCES openings (id) ON DELETE CASCADE,
    -- Nom relatif au dossier <données>/photos, jamais un chemin absolu.
    file_name  TEXT NOT NULL
               CHECK (trim(file_name) <> ''
                      AND file_name NOT LIKE '/%'
                      AND file_name NOT LIKE '%\%'
                      AND file_name NOT LIKE '%:%'
                      AND file_name NOT LIKE '%..%'),
    caption    TEXT,
    position   INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0)
);

CREATE TABLE meetings (
    id            INTEGER PRIMARY KEY,
    newsletter_id INTEGER NOT NULL REFERENCES newsletters (id) ON DELETE CASCADE,
    brand_name    TEXT NOT NULL CHECK (trim(brand_name) <> ''),
    meeting_date  TEXT,
    comment       TEXT,
    position      INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0)
);

CREATE TABLE collection_runs (
    id            INTEGER PRIMARY KEY,
    newsletter_id INTEGER NOT NULL REFERENCES newsletters (id) ON DELETE CASCADE,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'running'
                  CHECK (status IN ('running', 'success', 'partial', 'failed')),
    stats         TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(stats)),
    errors        TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(errors))
);

CREATE INDEX idx_articles_rubric ON articles (newsletter_id, rubric, position);
CREATE INDEX idx_articles_brand ON articles (brand_id);
CREATE INDEX idx_franchisees_newsletter ON franchisees (newsletter_id, position);
CREATE INDEX idx_franchisees_article ON franchisees (article_id);
CREATE INDEX idx_openings_newsletter ON openings (newsletter_id, position);
CREATE INDEX idx_opening_photos_opening ON opening_photos (opening_id, position);
CREATE INDEX idx_meetings_newsletter ON meetings (newsletter_id, position);
CREATE INDEX idx_collection_runs_newsletter ON collection_runs (newsletter_id, started_at);
