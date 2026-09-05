-- Query term coverage: which words of a request matched the catalog at all.
--
-- mosaic_search.search_fts already computes this signal and discards it. Its
-- salient-term selection keeps only lexemes satisfying an EXISTS against
-- product_document (09_search_functions.sql), so a term matching nothing is
-- dropped before the backoff loop runs. The request then proceeds on whatever
-- terms survived, and reciprocal rank fusion -- which weights by position, not
-- by score -- carries no memory that the dropped term was the one holding the
-- product identity.
--
-- This file keeps that signal instead of dropping it.
--
-- The distinction that matters is between a misspelling and an absence:
--
--   'hedfones' matches zero documents, but sits close to 'headphones' in the
--   corpus vocabulary. It is recoverable, and the trigram arm recovers it.
--
--   'a2342' matches zero documents and sits close to nothing. No arm can
--   recover it, because there is nothing to recover.
--
-- Trigram proximity separates those two for word-shaped tokens. It must NOT be
-- applied to identifier-shaped tokens: a model number close to a different
-- model number is a different product, not a repaired typo. PostgreSQL's own
-- text-search parser classifies the two token shapes, so the split is read from
-- ts_parse rather than from a hand-written pattern.
--
-- Two vocabularies, because the two questions have different answers:
--
--   corpus_lexeme          stemmed, from the same tsvector the FTS arm searches.
--                          Answers "does this term match a document" exactly.
--   corpus_surface_lexeme  unstemmed, from every text column a lexical or fuzzy
--                          arm reads. Answers "is there a close catalog term".
--
-- Measured on the live 500,000-product cluster on 2026-09-04: proximity against
-- the STEMMED vocabulary cannot answer the second question at all. Stemming
-- deletes exactly the characters a misspelling preserves, so 'hedfones' ->
-- 'hedfon' scores similarity 0.231 against 'headphon' while 'quarterly' ->
-- 'quarter', a real word the catalog simply does not carry, scores an identical
-- 0.231 against 'qualiti'. No floor separates them, in either direction, so the
-- Lab 1 anchor and an out-of-domain request were indistinguishable. Unstemmed,
-- the same two tokens score 0.462 and 0.200.

\echo '== Query term coverage =='

-- Corpus vocabulary with document frequencies, materialized from the same
-- tsvector column the FTS arm searches. ndoc turns "does this term match
-- anything" into one indexed lookup instead of a GIN probe per term.
--
-- SELECT * FROM mosaic_search.corpus_lexeme WHERE lexeme = 'a2342';
-- returning zero rows is the whole mechanism, in one statement.
CREATE TABLE IF NOT EXISTS mosaic_search.corpus_lexeme (
    lexeme text PRIMARY KEY,
    ndoc bigint NOT NULL,
    nentry bigint NOT NULL
);

COMMENT ON TABLE mosaic_search.corpus_lexeme IS
    'Distinct lexemes of mosaic_search.product_document.search_document with '
    'their document frequencies. Rebuilt by '
    'mosaic_search.refresh_corpus_lexeme(); derived data, never edited.';

-- The stemmed vocabulary is now read by exact lookup only, so its trigram index
-- has no reader. Dropped rather than left in place: an index whose query was
-- replaced is not a spare, it is 1,022,842 rows of storage and one more thing
-- that has to be rebuilt on every restore.
DROP INDEX IF EXISTS mosaic_search.corpus_lexeme_trgm_idx;

-- Surface vocabulary: the same words, unstemmed. This is the table the
-- neighbour lookup reads.
--
-- Built with the 'simple' configuration over every text column a retrieval arm
-- reads -- the four that compose search_document (06_retrieval_projection.sql)
-- plus trigram_text, which is what mosaic_search.search_trigram actually
-- matches against. The claim a `recoverable` verdict makes is "the trigram arm
-- can reach this term", so the vocabulary behind that claim has to be the text
-- that arm searches, not a stemmed projection of a different column.
--
-- Measured: including trigram_text adds 31 lexemes to the 1,023,117 the
-- search_document columns already supply -- the deliberate misspellings
-- 06_retrieval_projection.sql carries as aliases. Those 31 change NO verdict at
-- the floor below. 'hedfones' reaches 'headphones' at 0.333 from the
-- search_document columns alone, and 0.462 once 'hedphones' is in range; both
-- clear the floor. The gate does not rest on the planted typos.
CREATE TABLE IF NOT EXISTS mosaic_search.corpus_surface_lexeme (
    lexeme text PRIMARY KEY,
    ndoc bigint NOT NULL,
    nentry bigint NOT NULL
);

COMMENT ON TABLE mosaic_search.corpus_surface_lexeme IS
    'Distinct unstemmed lexemes of every mosaic_search.product_document text '
    'column a retrieval arm reads, with their document frequencies. Rebuilt by '
    'mosaic_search.refresh_corpus_lexeme(); derived data, never edited.';

CREATE INDEX IF NOT EXISTS corpus_surface_lexeme_trgm_idx
    ON mosaic_search.corpus_surface_lexeme USING gin (lexeme gin_trgm_ops);

-- Rebuild both vocabularies from the retrieval projection.
--
-- ts_stat scans every product document, so this belongs with seeding and index
-- construction rather than with a request. Call it after
-- mosaic_search.refresh_product_documents().
--
-- Measured on the live 500,000-product cluster on 2026-09-04 via
-- `make db-seed-corpus-lexeme`: 22 seconds for corpus_lexeme, which reads a
-- stored generated column, and 53 seconds for corpus_surface_lexeme, which
-- computes five tsvectors per row; 75 seconds for the whole CALL including both
-- ANALYZE steps. One-time, and skipping it is safe --
-- service.coverage reports `unavailable` against an empty vocabulary and every
-- surface behaves exactly as it did before coverage existed.
CREATE OR REPLACE PROCEDURE mosaic_search.refresh_corpus_lexeme()
LANGUAGE plpgsql
AS $$
BEGIN
    TRUNCATE mosaic_search.corpus_lexeme;
    INSERT INTO mosaic_search.corpus_lexeme (lexeme, ndoc, nentry)
    SELECT word, ndoc, nentry
    FROM ts_stat(
        'SELECT search_document FROM mosaic_search.product_document'
    );
    ANALYZE mosaic_search.corpus_lexeme;

    TRUNCATE mosaic_search.corpus_surface_lexeme;
    INSERT INTO mosaic_search.corpus_surface_lexeme (lexeme, ndoc, nentry)
    SELECT word, ndoc, nentry
    FROM ts_stat(
        $q$SELECT to_tsvector('simple', title_text)
               || to_tsvector('simple', identity_text)
               || to_tsvector('simple', feature_text)
               || to_tsvector('simple', body_text)
               || to_tsvector('simple', trigram_text)
             FROM mosaic_search.product_document$q$
    );
    ANALYZE mosaic_search.corpus_surface_lexeme;
END
$$;

-- Token shapes that carry an identity and cannot be repaired by proximity.
-- 'wh-c720' and 'a2342' parse as numhword and numword respectively; a near
-- neighbour of either is a different product.
CREATE OR REPLACE FUNCTION mosaic_search.is_identifier_token(token_kind text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT token_kind IN (
        'numword', 'numhword', 'uint', 'int', 'float', 'sfloat',
        'version', 'file', 'url', 'url_path', 'host', 'email'
    )
$$;

-- Token shapes a misspelling can be recovered from by trigram similarity.
CREATE OR REPLACE FUNCTION mosaic_search.is_word_token(token_kind text)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
    SELECT token_kind IN ('asciiword', 'word', 'asciihword', 'hword')
$$;

-- The signature changed when the floor stopped naming a function it never
-- called: the rescue is similarity(), not word_similarity(). CREATE OR REPLACE
-- cannot rename a parameter, so the old signature is dropped first. Re-running
-- this file on a cluster that already has it is the supported upgrade path.
DROP FUNCTION IF EXISTS mosaic_search.query_term_coverage(text, real);

-- One row per parsed token of a request, with the verdict on whether the
-- catalog contains anything it could refer to.
--
-- verdict values:
--   'matched'          the term appears in at least one product document
--   'recoverable'      no exact match, but a close catalog term exists and the
--                      trigram arm can reach it (the Lab 1 misspelling case)
--   'unmatched_anchor' no exact match and nothing close enough to recover; the
--                      request names something the catalog does not carry
--   'ignored'          punctuation, whitespace, or a stop word, which carry no
--                      retrieval identity either way
--
-- similarity_floor is MEASURED, on the live 500,000-product cluster on
-- 2026-09-04, against the 12 cases in data/evals/coverage_queries.jsonl. The
-- default here must equal coverage.similarity_floor in db/config/retrieval.yaml;
-- scripts/config_tripwire.py fails the build if it does not.
--
-- Every floor in (0.231, 0.250] classifies all 12 cases as the set expects.
-- 0.24 is the midpoint, which is the value that maximises the smaller of the two
-- margins. Both ends are one token wide:
--
--   rescued, and closest to the floor
--     'enough'      -> 'through'     0.250   +0.010   (C-105, must stay grounded)
--     'order'       -> 'or'          0.286   +0.046   (C-003)
--     'brick'       -> 'bridge'      0.300   +0.060   (C-001)
--   refused, and closest to the floor
--     'zylthorne'   -> 'corne'       0.231   -0.009   (C-005, invented brand)
--     'quarterly'   -> 'quality'     0.200   -0.040   (C-006, out of domain)
--
-- Read that honestly: 0.019 of trigram similarity is all that separates an
-- invented brand from an ordinary English word the catalog happens not to use,
-- and 'enough' is rescued by 'through', which is not a correction of it. The
-- word-shaped half of this gate is a weak signal calibrated on one corpus. The
-- identifier-shaped half is not: 'a2342' is refused because ts_parse calls it a
-- numword, at every floor, with no neighbour lookup at all.
--
-- The two anchors the workshop cannot afford to lose are decided with room:
--
--   C-101 'noice cancelng hedfones' -> grounded
--     'noice'    -> 'noice'      1.000   +0.760
--     'cancelng' -> 'canceling'  0.583   +0.343
--     'hedfones' -> 'hedphones'  0.462   +0.222   (0.333 vs 'headphones' with
--                                                  the alias lexemes excluded)
--   C-001 'replacement charging brick for model A2342' -> unanchored
--     'A2342' is a numword. Not floor-dependent in either direction.
CREATE OR REPLACE FUNCTION mosaic_search.query_term_coverage(
    q text,
    similarity_floor real DEFAULT 0.24
)
RETURNS TABLE (
    ordinal integer,
    token text,
    token_kind text,
    lexeme text,
    ndoc bigint,
    closest_lexeme text,
    closest_similarity real,
    verdict text
)
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
    WITH parsed AS (
        -- ts_parse emits the whole hyphenated token AND its parts. Keeping the
        -- parts would count 'wh-c720' three times, so only whole-token kinds
        -- reach the coverage test.
        SELECT row_number() OVER ()::integer AS ordinal,
               p.token,
               t.alias AS token_kind
        FROM ts_parse('default', coalesce(q, '')) AS p(tokid, token)
        JOIN ts_token_type('default') AS t(tokid, alias, description)
          ON t.tokid = p.tokid
    ),
    lexed AS (
        SELECT parsed.ordinal,
               parsed.token,
               parsed.token_kind,
               -- to_tsvector applies the same dictionary the FTS arm applies,
               -- so a stop word normalizes to nothing and is not a gap.
               (
                   SELECT arr[1]
                   FROM tsvector_to_array(
                       to_tsvector('english', parsed.token)
                   ) AS arr
                   LIMIT 1
               ) AS lexeme
        FROM parsed
        WHERE mosaic_search.is_word_token(parsed.token_kind)
           OR mosaic_search.is_identifier_token(parsed.token_kind)
    ),
    counted AS (
        SELECT lexed.ordinal,
               lexed.token,
               lexed.token_kind,
               lexed.lexeme,
               coalesce(corpus.ndoc, 0)::bigint AS ndoc
        FROM lexed
        LEFT JOIN mosaic_search.corpus_lexeme corpus
               ON corpus.lexeme = lexed.lexeme
    )
    SELECT counted.ordinal,
           counted.token,
           counted.token_kind,
           counted.lexeme,
           counted.ndoc,
           near.lexeme AS closest_lexeme,
           near.similarity AS closest_similarity,
           CASE
               WHEN counted.lexeme IS NULL THEN 'ignored'
               WHEN counted.ndoc > 0 THEN 'matched'
               WHEN mosaic_search.is_identifier_token(counted.token_kind)
                   THEN 'unmatched_anchor'
               WHEN near.similarity >= similarity_floor
                   THEN 'recoverable'
               ELSE 'unmatched_anchor'
           END AS verdict
    FROM counted
    -- The neighbour lookup runs only where it can change the verdict: a
    -- word-shaped token that matched nothing. It compares the token as written
    -- against the unstemmed vocabulary, because the characters a misspelling
    -- preserves are the ones the stemmer removes.
    --
    -- `%` is index-backed by corpus_surface_lexeme_trgm_idx and gated by
    -- pg_trgm.similarity_threshold, which is 0.18 on this cluster
    -- (candidate_generation.trigram_index_gate.similarity_threshold). The floor
    -- must stay at or above that gate: below it the index would prune
    -- neighbours the floor would have accepted, and the floor would silently
    -- stop being the thing that decides.
    LEFT JOIN LATERAL (
        SELECT vocabulary.lexeme,
               similarity(vocabulary.lexeme, lower(counted.token)) AS similarity
        FROM mosaic_search.corpus_surface_lexeme vocabulary
        WHERE counted.lexeme IS NOT NULL
          AND counted.ndoc = 0
          AND mosaic_search.is_word_token(counted.token_kind)
          AND vocabulary.lexeme % lower(counted.token)
        ORDER BY similarity(vocabulary.lexeme, lower(counted.token)) DESC,
                 vocabulary.lexeme
        LIMIT 1
    ) AS near ON true
    ORDER BY counted.ordinal;
$$;

COMMENT ON FUNCTION mosaic_search.query_term_coverage(text, real) IS
    'Per-token catalog coverage for a request. Distinguishes a misspelling '
    '(recoverable by the trigram arm) from an absence (recoverable by nothing). '
    'Reads mosaic_search.corpus_lexeme for exact matches and '
    'mosaic_search.corpus_surface_lexeme for neighbours; '
    'mosaic_search.refresh_corpus_lexeme() must have populated both.';
