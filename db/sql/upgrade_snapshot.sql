\set ON_ERROR_STOP on
\echo '== Mosaic snapshot upgrade =='
\echo 'Replaying the current idempotent core model while preserving search_trigram.'

\set preserve_search_trigram true
\ir install.sql
\unset preserve_search_trigram

DO $upgrade_check$
DECLARE
    function_config text[];
BEGIN
    IF to_regprocedure(
        'mosaic_search.search_trigram(text,jsonb,integer,real)'
    ) IS NULL THEN
        RAISE EXCEPTION
            'snapshot upgrade requires mosaic_search.search_trigram(text,jsonb,integer,real); found no canonical function; fix: restore the canonical Mosaic snapshot before running db-upgrade-snapshot';
    END IF;

    SELECT p.proconfig
    INTO function_config
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'mosaic_search'
      AND p.proname = 'search_trigram'
      AND pg_get_function_identity_arguments(p.oid) =
          'q text, f jsonb, candidate_limit integer, minimum_similarity real';

    IF function_config IS NULL
       OR NOT function_config @> ARRAY[
           'pg_trgm.similarity_threshold=0.18',
           'pg_trgm.word_similarity_threshold=0.5'
       ] THEN
        RAISE EXCEPTION
            'snapshot search_trigram has settings %, expected similarity_threshold=0.18 and word_similarity_threshold=0.5; fix: restore snapshot mosaic-catalog-500k-cohere-v4-20260809 rather than replacing the function as the retrieval role',
            coalesce(function_config::text, 'NULL');
    END IF;
END
$upgrade_check$;

\echo 'Snapshot upgrade complete; canonical search_trigram preserved and validated.'
