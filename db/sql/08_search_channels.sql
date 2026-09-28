\set ON_ERROR_STOP on

-- The three retrieval channels and the filters they share. Each channel returns
-- its own ranked candidates; labs/lab1_retrieve/hybrid_search.sql fuses them.

CREATE OR REPLACE FUNCTION mosaic_search.matches_filter_values(
    product_domain mosaic.product_domain,
    product_category_key text,
    product_brand_name text,
    product_price_cents bigint,
    product_availability mosaic.availability_status,
    product_rating numeric,
    product_attributes jsonb,
    product_is_refurbished boolean,
    product_is_sponsored boolean,
    f jsonb
)
RETURNS boolean
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
SELECT
    (NOT (f ? 'domain') OR product_domain = (f->>'domain')::mosaic.product_domain) AND
    (NOT (f ? 'category_key') OR product_category_key = f->>'category_key') AND
    (NOT (f ? 'brand') OR lower(product_brand_name) = lower(f->>'brand')) AND
    (
        NOT (f ? 'brands')
        OR jsonb_array_length(f->'brands') = 0
        OR (f->'brands') ? product_brand_name
    ) AND
    (NOT (f ? 'min_price_cents') OR product_price_cents >= (f->>'min_price_cents')::bigint) AND
    (NOT (f ? 'max_price_cents') OR product_price_cents <= (f->>'max_price_cents')::bigint) AND
    (
        NOT (f ? 'availability')
        OR product_availability = (f->>'availability')::mosaic.availability_status
    ) AND
    (
        NOT coalesce((f->>'in_stock_only')::boolean, false)
        OR product_availability IN ('in_stock','low_stock')
    ) AND
    (NOT (f ? 'min_rating') OR coalesce(product_rating, 0) >= (f->>'min_rating')::numeric) AND
    (NOT (f ? 'attributes') OR product_attributes @> (f->'attributes')) AND
    (
        coalesce((f->>'include_refurbished')::boolean, false)
        OR NOT product_is_refurbished
    ) AND
    (
        coalesce((f->>'include_sponsored')::boolean, false)
        OR NOT product_is_sponsored
    )
$$;

CREATE OR REPLACE FUNCTION mosaic_search.matches_filters(
    d mosaic_search.product_document,
    f jsonb
)
RETURNS boolean
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
SELECT mosaic_search.matches_filter_values(
    (d).domain,
    (d).category_key,
    (d).brand_name,
    (d).price_cents,
    (d).availability,
    (d).rating,
    (d).attributes,
    (d).is_refurbished,
    (d).is_sponsored,
    f
)
$$;

CREATE OR REPLACE FUNCTION mosaic_search.configure_hnsw(
    p_ef_search integer DEFAULT 100,
    p_iterative_scan text DEFAULT 'relaxed_order',
    p_max_scan_tuples integer DEFAULT 20000,
    p_scan_mem_multiplier real DEFAULT 2
)
RETURNS void
LANGUAGE plpgsql
VOLATILE
AS $$
BEGIN
    IF p_ef_search < 1 OR p_ef_search > 1000 THEN
        RAISE EXCEPTION 'ef_search must be between 1 and 1000';
    END IF;
    IF p_iterative_scan NOT IN ('off', 'strict_order', 'relaxed_order') THEN
        RAISE EXCEPTION 'iterative_scan must be off, strict_order, or relaxed_order';
    END IF;
    IF p_max_scan_tuples < 1 THEN
        RAISE EXCEPTION 'max_scan_tuples must be positive';
    END IF;
    IF p_scan_mem_multiplier < 1 THEN
        RAISE EXCEPTION 'scan_mem_multiplier must be at least 1';
    END IF;

    PERFORM set_config('hnsw.ef_search', p_ef_search::text, true);
    PERFORM set_config('hnsw.iterative_scan', p_iterative_scan, true);
    PERFORM set_config('hnsw.max_scan_tuples', p_max_scan_tuples::text, true);
    PERFORM set_config('hnsw.scan_mem_multiplier', p_scan_mem_multiplier::text, true);
END
$$;

CREATE OR REPLACE FUNCTION mosaic_search.search_fts(
    q text,
    f jsonb DEFAULT '{}'::jsonb,
    candidate_limit integer DEFAULT 120
)
RETURNS TABLE (
    product_id bigint,
    fts_score real,
    fts_rank bigint
)
LANGUAGE plpgsql
STABLE
PARALLEL SAFE
AS $$
DECLARE
    strict_tsq tsquery := websearch_to_tsquery('english', q);
    salient_terms text[];
    active_tsq tsquery;
    term_count integer;
    returned_rows integer;
BEGIN
    -- Exact identity and well-formed lexical queries should take the most
    -- selective GIN path. The previous implementation always widened the query
    -- to OR, then scored 130K rows for a common five-term Shop query.
    RETURN QUERY
    WITH scored AS (
        SELECT d.product_id,
               (ts_rank_cd(d.search_document, strict_tsq, 32) + 1.0)::real AS score
        FROM mosaic_search.product_document d
        WHERE d.search_document @@ strict_tsq
          AND (NOT (f ? 'domain') OR d.domain = (f->>'domain')::mosaic.product_domain)
          AND (NOT (f ? 'category_key') OR d.category_key = f->>'category_key')
          AND (NOT (f ? 'attributes') OR d.attributes @> (f->'attributes'))
          AND mosaic_search.matches_filter_values(
              d.domain, d.category_key, d.brand_name, d.price_cents,
              d.availability, d.rating, d.attributes, d.is_refurbished,
              d.is_sponsored, f
          )
        ORDER BY score DESC, d.product_id
        LIMIT greatest(candidate_limit, 1)
    )
    SELECT scored.product_id, scored.score,
           row_number() OVER (ORDER BY scored.score DESC, scored.product_id)
    FROM scored;
    GET DIAGNOSTICS returned_rows = ROW_COUNT;
    IF returned_rows > 0 THEN
        RETURN;
    END IF;

    -- A conversational query often contains a typo, a price, or comparison
    -- language that makes the strict conjunction unsatisfiable. Select at most
    -- four substantive lexemes that occur in the corpus, then back off from a
    -- four-term conjunction only when it yields no eligible rows. Each branch
    -- remains a selective GIN query; no branch falls back to scoring every row
    -- that contains any one common word.
    SELECT array_agg(lexeme ORDER BY length(lexeme) DESC, lexeme)
    INTO salient_terms
    FROM (
        SELECT lexeme
        FROM unnest(tsvector_to_array(to_tsvector('english', q))) AS term(lexeme)
        WHERE lexeme !~ '^[0-9]+$'
          AND lexeme NOT IN (
              'altern', 'best', 'cheap', 'cheaper', 'choos', 'compar',
              'evid', 'explain', 'find', 'need', 'option', 'recommend',
              'strongest', 'want'
          )
          AND EXISTS (
              SELECT 1
              FROM mosaic_search.product_document corpus
              WHERE corpus.search_document
                    @@ to_tsquery('english', quote_literal(lexeme))
          )
        ORDER BY length(lexeme) DESC, lexeme
        LIMIT 4
    ) AS selected;

    term_count := coalesce(cardinality(salient_terms), 0);
    WHILE term_count > 0 LOOP
        SELECT to_tsquery(
                   'english',
                   string_agg(quote_literal(term), ' & ' ORDER BY ordinal)
               )
        INTO active_tsq
        FROM unnest(salient_terms[1:term_count])
             WITH ORDINALITY AS selected(term, ordinal);

        RETURN QUERY
        WITH scored AS (
            SELECT d.product_id,
                   ts_rank_cd(d.search_document, active_tsq, 32)::real AS score
            FROM mosaic_search.product_document d
            WHERE d.search_document @@ active_tsq
              AND (NOT (f ? 'domain') OR d.domain = (f->>'domain')::mosaic.product_domain)
              AND (NOT (f ? 'category_key') OR d.category_key = f->>'category_key')
              AND (NOT (f ? 'attributes') OR d.attributes @> (f->'attributes'))
              AND mosaic_search.matches_filter_values(
                  d.domain, d.category_key, d.brand_name, d.price_cents,
                  d.availability, d.rating, d.attributes, d.is_refurbished,
                  d.is_sponsored, f
              )
            ORDER BY score DESC, d.product_id
            LIMIT greatest(candidate_limit, 1)
        )
        SELECT scored.product_id, scored.score,
               row_number() OVER (ORDER BY scored.score DESC, scored.product_id)
        FROM scored;
        GET DIAGNOSTICS returned_rows = ROW_COUNT;
        IF returned_rows > 0 THEN
            RETURN;
        END IF;
        term_count := term_count - 1;
    END LOOP;
END
$$;

CREATE OR REPLACE FUNCTION mosaic_search.search_trigram(
    q text,
    f jsonb DEFAULT '{}'::jsonb,
    candidate_limit integer DEFAULT 80,
    minimum_similarity real DEFAULT 0.20
)
RETURNS TABLE (
    product_id bigint,
    trigram_score real,
    trigram_rank bigint
)
LANGUAGE plpgsql
STABLE
PARALLEL SAFE
AS $$
DECLARE
    returned_rows integer;
BEGIN
    -- Word similarity is the intended typo-recovery path for a query embedded
    -- in the longer identity/alias document. Running it first avoids the broad
    -- whole-string gate that admitted 130K index hits for a normal Shop query.
    RETURN QUERY
    WITH scored AS (
        SELECT d.product_id,
               greatest(
                   similarity(d.trigram_text, lower(q)),
                   word_similarity(lower(q), d.trigram_text),
                   strict_word_similarity(lower(q), d.trigram_text)
               )::real AS score
        FROM mosaic_search.product_document d
        WHERE (NOT (f ? 'domain') OR d.domain = (f->>'domain')::mosaic.product_domain)
          AND (NOT (f ? 'category_key') OR d.category_key = f->>'category_key')
          AND (NOT (f ? 'attributes') OR d.attributes @> (f->'attributes'))
          AND mosaic_search.matches_filter_values(
                  d.domain, d.category_key, d.brand_name, d.price_cents,
                  d.availability, d.rating, d.attributes, d.is_refurbished,
                  d.is_sponsored, f
              )
          AND lower(q) <% d.trigram_text
          AND greatest(
              similarity(d.trigram_text, lower(q)),
              word_similarity(lower(q), d.trigram_text),
              strict_word_similarity(lower(q), d.trigram_text)
          ) >= minimum_similarity
        ORDER BY score DESC, d.product_id
        LIMIT greatest(candidate_limit, 1)
    )
    SELECT scored.product_id, scored.score,
           row_number() OVER (ORDER BY scored.score DESC, scored.product_id)
    FROM scored;
    GET DIAGNOSTICS returned_rows = ROW_COUNT;
    IF returned_rows > 0 THEN
        RETURN;
    END IF;

    -- Some misspellings are separated by intervening intent words, so the
    -- phrase-oriented word gate can legitimately return nothing. The
    -- whole-string gate remains a fallback, but it is no longer OR'd into every
    -- request and therefore cannot dominate the common path.
    RETURN QUERY
    WITH scored AS (
        SELECT d.product_id,
               greatest(
                   similarity(d.trigram_text, lower(q)),
                   word_similarity(lower(q), d.trigram_text),
                   strict_word_similarity(lower(q), d.trigram_text)
               )::real AS score
        FROM mosaic_search.product_document d
        WHERE (NOT (f ? 'domain') OR d.domain = (f->>'domain')::mosaic.product_domain)
          AND (NOT (f ? 'category_key') OR d.category_key = f->>'category_key')
          AND (NOT (f ? 'attributes') OR d.attributes @> (f->'attributes'))
          AND mosaic_search.matches_filter_values(
                  d.domain, d.category_key, d.brand_name, d.price_cents,
                  d.availability, d.rating, d.attributes, d.is_refurbished,
                  d.is_sponsored, f
              )
          AND d.trigram_text % lower(q)
          AND greatest(
              similarity(d.trigram_text, lower(q)),
              word_similarity(lower(q), d.trigram_text),
              strict_word_similarity(lower(q), d.trigram_text)
          ) >= minimum_similarity
        ORDER BY score DESC, d.product_id
        LIMIT greatest(candidate_limit, 1)
    )
    SELECT scored.product_id, scored.score,
           row_number() OVER (ORDER BY scored.score DESC, scored.product_id)
    FROM scored;
END
$$;

CREATE OR REPLACE FUNCTION mosaic_search.search_vector(
    query_embedding vector(1024),
    f jsonb DEFAULT '{}'::jsonb,
    candidate_limit integer DEFAULT 150
)
RETURNS TABLE (
    product_id bigint,
    cosine_distance double precision,
    semantic_score real,
    semantic_rank bigint
)
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $$
WITH scored AS (
    SELECT d.product_id,
           d.embedding <=> query_embedding AS distance
    FROM mosaic_search.product_document d
    WHERE d.embedding IS NOT NULL
      AND (NOT (f ? 'domain') OR d.domain = (f->>'domain')::mosaic.product_domain)
      AND (NOT (f ? 'category_key') OR d.category_key = f->>'category_key')
      AND (NOT (f ? 'attributes') OR d.attributes @> (f->'attributes'))
      AND mosaic_search.matches_filter_values(
          d.domain, d.category_key, d.brand_name, d.price_cents,
          d.availability, d.rating, d.attributes, d.is_refurbished,
          d.is_sponsored, f
      )
    ORDER BY d.embedding <=> query_embedding
    LIMIT greatest(candidate_limit, 1)
)
SELECT product_id,
       distance,
       (1 - distance)::real,
       row_number() OVER (ORDER BY distance, product_id)
FROM scored
$$;
