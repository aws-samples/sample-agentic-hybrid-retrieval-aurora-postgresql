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
--   'hedfones' matches zero documents, but sits close to 'headphon' in the
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

\echo '== Query term coverage =='

-- Corpus vocabulary with document frequencies, materialized from the same
-- tsvector column the FTS arm searches. Two jobs:
--
--   1. ndoc turns "does this term match anything" into one indexed lookup
--      instead of a GIN probe per term.
--   2. The trigram index over the vocabulary answers "is there a close term"
--      without scanning 500,000 product documents.
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

CREATE INDEX IF NOT EXISTS corpus_lexeme_trgm_idx
    ON mosaic_search.corpus_lexeme USING gin (lexeme gin_trgm_ops);

-- Rebuild the vocabulary from the retrieval projection.
--
-- ts_stat scans every product document, so this belongs with seeding and index
-- construction rather than with a request. Call it after
-- mosaic_search.refresh_product_documents().
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
-- word_similarity_floor is UNMEASURED. It separates a misspelling from an
-- absence for word-shaped tokens only, and the value that does so on this
-- corpus has to be established against the live cluster before it is promoted
-- into db/config/retrieval.yaml. Until then it stays a parameter default so no
-- caller can mistake it for a measured number.
CREATE OR REPLACE FUNCTION mosaic_search.query_term_coverage(
    q text,
    word_similarity_floor real DEFAULT 0.40
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
               WHEN near.similarity >= word_similarity_floor
                   THEN 'recoverable'
               ELSE 'unmatched_anchor'
           END AS verdict
    FROM counted
    -- The neighbour lookup runs only where it can change the verdict: a
    -- word-shaped token that matched nothing. `%` is index-backed by
    -- corpus_lexeme_trgm_idx and gated by pg_trgm.similarity_threshold.
    LEFT JOIN LATERAL (
        SELECT corpus.lexeme,
               similarity(corpus.lexeme, counted.lexeme) AS similarity
        FROM mosaic_search.corpus_lexeme corpus
        WHERE counted.lexeme IS NOT NULL
          AND counted.ndoc = 0
          AND mosaic_search.is_word_token(counted.token_kind)
          AND corpus.lexeme % counted.lexeme
        ORDER BY similarity(corpus.lexeme, counted.lexeme) DESC, corpus.lexeme
        LIMIT 1
    ) AS near ON true
    ORDER BY counted.ordinal;
$$;

COMMENT ON FUNCTION mosaic_search.query_term_coverage(text, real) IS
    'Per-token catalog coverage for a request. Distinguishes a misspelling '
    '(recoverable by the trigram arm) from an absence (recoverable by nothing). '
    'Reads mosaic_search.corpus_lexeme, which '
    'mosaic_search.refresh_corpus_lexeme() must have populated.';
