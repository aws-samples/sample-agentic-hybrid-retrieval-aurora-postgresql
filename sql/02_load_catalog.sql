\set ON_ERROR_STOP on

-- Default psql convenience path. For any other path, use scripts/load_catalog.py.
TRUNCATE TABLE catalog_stage.product_raw;
\copy catalog_stage.product_raw FROM PROGRAM 'gzip -dc data/full/products_consumer_electronics.csv.gz' WITH (FORMAT csv, HEADER true)
\copy catalog_stage.product_raw FROM PROGRAM 'gzip -dc data/full/products_running_fitness.csv.gz' WITH (FORMAT csv, HEADER true)
\copy catalog_stage.product_raw FROM PROGRAM 'gzip -dc data/full/products_home_office.csv.gz' WITH (FORMAT csv, HEADER true)
\i sql/02_upsert_from_stage.sql

SELECT domain, count(*) AS products
FROM catalog.product
GROUP BY domain
ORDER BY domain;
