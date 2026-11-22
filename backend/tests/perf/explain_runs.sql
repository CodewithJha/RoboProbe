-- T-081d GET /campaigns/{id}/runs?sort=-ordinal, page five of the Locust profile.
\set page_size 10
\set pages_before 4
ANALYZE campaigns;
ANALYZE runs;

SELECT ordinal AS cursor_ordinal, id AS cursor_id
FROM runs
WHERE campaign_id = :'campaign_id'::uuid
ORDER BY ordinal DESC, id DESC
OFFSET (:page_size * :pages_before - 1) LIMIT 1
\gset

EXPLAIN (ANALYZE, BUFFERS)
SELECT runs.*
FROM runs
WHERE campaign_id = :'campaign_id'::uuid
  AND (ordinal, id) < (:'cursor_ordinal'::integer, :'cursor_id'::uuid)
ORDER BY ordinal DESC, id DESC
LIMIT (:page_size + 1);
