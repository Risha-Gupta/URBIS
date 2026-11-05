-- URBIS Phase 7: the spatial queries the API is built on.
-- Run:  psql "$DSN" -v lon=24.7536 -v lat=59.437 -v radius=300 -f db/example_queries.sql

\echo '== Q1  buildings NEAR a point (radius in metres), nearest first'
WITH p AS (SELECT ST_Transform(ST_SetSRID(ST_MakePoint(:lon, :lat), 4326), 3301) AS g)
SELECT building_id, round(ST_Distance(centroid, p.g)::numeric, 1) AS dist_m, action,
       round(model_confidence::numeric, 3) AS conf, round(annual_kwh::numeric) AS kwh, solar_reliability
FROM v_building_summary, p
WHERE ST_DWithin(centroid, p.g, :radius)
ORDER BY centroid <-> p.g
LIMIT 10;

\echo '== Q2  buildings WITHIN a bounding box (lon/lat), with footprint intersection'
WITH env AS (SELECT ST_Transform(ST_MakeEnvelope(24.74, 59.43, 24.77, 59.445, 4326), 3301) AS g)
SELECT count(*) AS buildings_in_box, count(*) FILTER (WHERE action = 'ESCALATE') AS escalated,
       round((sum(annual_kwh) / 1000)::numeric) AS mwh_per_year
FROM v_building_summary, env
WHERE ST_Intersects(footprint, env.g);

\echo '== Q3  uncertain or failed reconstructions'
SELECT status, action, count(*) FROM v_building_summary
WHERE status <> 'completed' OR action = 'ESCALATE'
GROUP BY 1, 2 ORDER BY 1, 2;

\echo '== Q4  top roofs by yield, reliable estimates only'
SELECT building_id, round(annual_kwh::numeric) AS kwh_per_year, round(total_roof_area_m2::numeric) AS roof_m2,
       action, solar_reliability
FROM v_building_summary
WHERE solar_reliability = 'ok'
ORDER BY annual_kwh DESC
LIMIT 5;

\echo '== Q5  solar yield at risk on the held-out half (ground truth, reports only)'
SELECT round((sum(s.annual_kwh) FILTER (WHERE e.is_bad = 1 AND v.action <> 'ESCALATE') / sum(s.annual_kwh))::numeric, 3)
         AS share_in_accepted_bad_rule,
       round((sum(s.annual_kwh) FILTER (WHERE e.is_bad = 1) / sum(s.annual_kwh))::numeric, 3) AS share_in_bad_accept_all,
       round((sum(s.annual_kwh) FILTER (WHERE e.is_bad = 1 AND v.action <> 'ESCALATE') / 1e6)::numeric, 2) AS gwh_rule
FROM evaluation e
JOIN solar_buildings s USING (building_id)
JOIN v_building_summary v USING (building_id)
WHERE e.half = 'hold';
