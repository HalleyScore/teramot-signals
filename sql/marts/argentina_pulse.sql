-- Argentina pulse: one row per indicator, with the latest value, the previous one, ~30 days ago,
-- ~1 year ago, the last year's min and max, and two years of history packed as JSON (`points`).
-- Sections: fx (currencies), bcra (monetary variables), supermarkets (supermarket sales by
-- jurisdiction), fuel_history / fuel_province / fuel_brand / fuel_national (fuel prices),
-- weather (forecast by city) and meta (latest extraction of each source).
-- Columns: section, key, name, category, unit, last_date, last_value, prev_value, ref_value,
-- extra1, extra2, extra3, n, points. For series: extra1 = one year ago, extra2/extra3 = min/max over
-- the last year. For fuel: last_value = median, extra1/2/3 = mean/min/max. For weather:
-- extra1/extra2 = lat/lon and points = [date, max, min, precipitation].
CREATE OR REPLACE VIEW argentina_pulse AS
WITH
labels(sec, key, name, category, unit) AS (
    VALUES
    ('fx', 'USD', 'US dollar', 'Currencies', 'ARS per unit'),
    ('fx', 'EUR', 'Euro', 'Currencies', 'ARS per unit'),
    ('fx', 'BRL', 'Brazilian real', 'Currencies', 'ARS per unit'),
    ('fx', 'GBP', 'Pound sterling', 'Currencies', 'ARS per unit'),
    ('fx', 'CNY', 'Chinese yuan', 'Currencies', 'ARS per unit'),
    ('fx', 'CHF', 'Swiss franc', 'Currencies', 'ARS per unit'),
    ('fx', 'JPY', 'Japanese yen', 'Currencies', 'ARS per unit'),
    ('fx', 'CLP', 'Chilean peso', 'Currencies', 'ARS per unit'),
    ('fx', 'UYU', 'Uruguayan peso', 'Currencies', 'ARS per unit'),
    ('fx', 'XAU', 'Gold', 'Metals', 'USD per ounce'),
    ('fx', 'XAG', 'Silver', 'Metals', 'USD per ounce'),
    ('bcra', 'international_reserves_musd', 'International reserves', 'Reserves', 'USD millions'),
    ('bcra', 'usd_retail_avg_selling_rate', 'Retail dollar', 'Exchange rate', 'ARS per USD'),
    ('bcra', 'usd_wholesale_rate_com_a3500', 'Wholesale dollar', 'Exchange rate', 'ARS per USD'),
    ('bcra', 'badlar_private_banks_apr', 'BADLAR private banks', 'Interest rates', '% nominal annual'),
    ('bcra', 'tamar_private_banks_apr', 'TAMAR private banks', 'Interest rates', '% nominal annual'),
    ('bcra', 'time_deposit_30d_apr', '30-day time deposit', 'Interest rates', '% nominal annual'),
    ('bcra', 'personal_loans_apr', 'Personal loans', 'Interest rates', '% nominal annual'),
    ('bcra', 'monetary_base_mars', 'Monetary base', 'Money', 'ARS millions'),
    ('bcra', 'total_deposits_mars', 'Total deposits', 'Money', 'ARS millions'),
    ('bcra', 'private_sector_loans_mars', 'Private sector loans', 'Money', 'ARS millions'),
    ('bcra', 'monthly_inflation_pct', 'Monthly inflation', 'Prices', '%'),
    ('bcra', 'yoy_inflation_pct', 'Year-over-year inflation', 'Prices', '%'),
    ('bcra', 'expected_inflation_12m_pct', 'Expected inflation, 12 months', 'Prices', '%'),
    ('bcra', 'cer', 'CER', 'Indices', 'index'),
    ('bcra', 'uva', 'UVA', 'Indices', 'ARS'),
    ('bcra', 'icl_rent_index', 'ICL rent index', 'Indices', 'index')
),
fxd AS (
    SELECT 'fx' AS sec, split_part(variable, '.', 1) AS key, ref_date AS f, value AS v
    FROM bcra__fx_history__latest
    WHERE variable = split_part(variable, '.', 1) ||
          CASE WHEN split_part(variable, '.', 1) IN ('XAU', 'XAG') THEN '.usd_parity' ELSE '.rate' END
      AND split_part(variable, '.', 1) IN (SELECT key FROM labels WHERE sec = 'fx')
      AND ref_date >= current_date - INTERVAL 800 DAY
),
bcrad AS (
    SELECT 'bcra' AS sec, variable AS key, ref_date AS f, value AS v
    FROM bcra__monetary_series__latest
    WHERE variable IN (SELECT key FROM labels WHERE sec = 'bcra')
      AND ref_date >= current_date - INTERVAL 800 DAY
),
superd AS (
    SELECT 'supermarkets' AS sec, jurisdiction AS key, date AS f, sales_total AS v
    FROM indec__supermarkets_by_province__latest
    WHERE date >= current_date - INTERVAL 800 DAY
),
fuel_obs AS (
    -- Each daily extraction of current prices carries the latest price reported per station;
    -- the union of all extractions is the history.
    SELECT DISTINCT cuit, direccion, producto, precio,
        TRY_CAST(left(fecha_vigencia, 10) AS DATE) AS fv, provincia, empresabandera
    FROM energia_ckan__pump_prices_current
    WHERE tipohorario = 'Diurno' AND precio > 0
),
fueld AS (
    SELECT 'fuel_history' AS sec, producto AS key, CAST(date_trunc('month', fv) AS DATE) AS f,
        quantile_cont(precio, 0.5) AS v
    FROM fuel_obs WHERE fv >= current_date - INTERVAL 800 DAY
    GROUP BY 1, 2, 3
),
ser AS (
    SELECT * FROM fxd UNION ALL SELECT * FROM bcrad UNION ALL SELECT * FROM superd
    UNION ALL SELECT * FROM fueld
),
serw AS (
    SELECT *, max(f) OVER (PARTITION BY sec, key) AS mf,
        row_number() OVER (PARTITION BY sec, key ORDER BY f DESC) AS rn
    FROM ser WHERE v IS NOT NULL
),
seragg AS (
    SELECT sec, key,
        CAST(max(f) AS VARCHAR) AS last_date,
        arg_max(v, f) AS last_value,
        max(v) FILTER (WHERE rn = 2) AS prev_value,
        arg_max(v, f) FILTER (WHERE f <= mf - INTERVAL 30 DAY) AS ref_value,
        arg_max(v, f) FILTER (WHERE f <= mf - INTERVAL 365 DAY) AS extra1,
        min(v) FILTER (WHERE f > mf - INTERVAL 365 DAY) AS extra2,
        max(v) FILTER (WHERE f > mf - INTERVAL 365 DAY) AS extra3,
        count(*) AS n,
        to_json(list([CAST(f AS VARCHAR), CAST(round(v, 4) AS VARCHAR)] ORDER BY f)
            FILTER (WHERE f > mf - INTERVAL 730 DAY))::VARCHAR AS points
    FROM serw GROUP BY sec, key
),
serfinal AS (
    SELECT s.sec AS section, s.key,
        coalesce(nm.name, s.key) AS name,
        coalesce(nm.category, CASE s.sec WHEN 'supermarkets' THEN 'Supermarkets' WHEN 'fuel_history' THEN 'Fuel' END) AS category,
        coalesce(nm.unit, CASE s.sec WHEN 'supermarkets' THEN 'ARS (thousands)' WHEN 'fuel_history' THEN 'ARS per liter' END) AS unit,
        s.last_date, s.last_value, s.prev_value, s.ref_value, s.extra1, s.extra2, s.extra3, s.n, s.points
    FROM seragg s LEFT JOIN labels nm ON s.sec = nm.sec AND s.key = nm.key
),
weather_run AS (
    SELECT max(extraction_date) AS ed FROM open_meteo__forecast
),
weatherfinal AS (
    SELECT 'weather' AS section, p.locality_id AS key, any_value(p.locality) AS name,
        any_value(p.province) AS category, '°C / mm' AS unit,
        CAST(max(p.date) AS VARCHAR) AS last_date,
        CAST(NULL AS DOUBLE) AS last_value, CAST(NULL AS DOUBLE) AS prev_value, CAST(NULL AS DOUBLE) AS ref_value,
        any_value(p.lat) AS extra1, any_value(p.lon) AS extra2, CAST(NULL AS DOUBLE) AS extra3,
        count(*) AS n,
        to_json(list([CAST(p.date AS VARCHAR), CAST(round(p.temp_max, 1) AS VARCHAR),
            CAST(round(p.temp_min, 1) AS VARCHAR), CAST(round(coalesce(p.precipitation_mm, 0), 1) AS VARCHAR)]
            ORDER BY p.date))::VARCHAR AS points
    FROM open_meteo__forecast p, weather_run c
    WHERE p.extraction_date = c.ed AND p.temp_max IS NOT NULL AND p.temp_min IS NOT NULL
    GROUP BY p.locality_id
),
fuel_current AS (
    SELECT producto, provincia, empresabandera, arg_max(precio, fv) AS pr, max(fv) AS f
    FROM fuel_obs GROUP BY cuit, direccion, producto, provincia, empresabandera
),
cur AS (
    SELECT c.*, m.mf FROM fuel_current c, (SELECT max(f) AS mf FROM fuel_current) m
    WHERE c.f >= m.mf - INTERVAL 120 DAY
),
fuelfinal AS (
    SELECT 'fuel_province' AS section, producto AS key, coalesce(provincia, 'NO DATA') AS name,
        producto AS category, 'ARS per liter' AS unit, CAST(max(mf) AS VARCHAR) AS last_date,
        quantile_cont(pr, 0.5) AS last_value, CAST(NULL AS DOUBLE) AS prev_value, CAST(NULL AS DOUBLE) AS ref_value,
        avg(pr) AS extra1, min(pr) AS extra2, max(pr) AS extra3, count(*) AS n, CAST(NULL AS VARCHAR) AS points
    FROM cur GROUP BY producto, provincia
    UNION ALL
    SELECT 'fuel_brand', producto, empresabandera, producto, 'ARS per liter', CAST(max(mf) AS VARCHAR),
        quantile_cont(pr, 0.5), NULL, NULL, avg(pr), min(pr), max(pr), count(*), NULL
    FROM cur WHERE empresabandera IS NOT NULL GROUP BY producto, empresabandera HAVING count(*) >= 15
    UNION ALL
    SELECT 'fuel_national', producto, 'Argentina', producto, 'ARS per liter', CAST(max(mf) AS VARCHAR),
        quantile_cont(pr, 0.5), NULL, NULL, avg(pr), min(pr), max(pr), count(*), NULL
    FROM cur GROUP BY producto
),
metafinal AS (
    SELECT 'meta' AS section, key, name, 'Last update' AS category, '' AS unit,
        CAST(last_extraction AS VARCHAR) AS last_date,
        CAST(NULL AS DOUBLE) AS last_value, CAST(NULL AS DOUBLE) AS prev_value, CAST(NULL AS DOUBLE) AS ref_value,
        CAST(NULL AS DOUBLE) AS extra1, CAST(NULL AS DOUBLE) AS extra2, CAST(NULL AS DOUBLE) AS extra3,
        CAST(NULL AS BIGINT) AS n, CAST(NULL AS VARCHAR) AS points
    FROM (
        SELECT 'fx' AS key, 'Currencies' AS name, max(extracted_at) AS last_extraction FROM bcra__fx_history
        UNION ALL SELECT 'bcra', 'BCRA variables', max(extracted_at) FROM bcra__monetary_series
        UNION ALL SELECT 'weather', 'Weather', max(extracted_at) FROM open_meteo__forecast
        UNION ALL SELECT 'fuel', 'Fuel', max(extracted_at) FROM energia_ckan__pump_prices_current
        UNION ALL SELECT 'supermarkets', 'Supermarkets', max(extracted_at) FROM indec__supermarkets_by_province
    )
)
SELECT * FROM serfinal
UNION ALL SELECT * FROM weatherfinal
UNION ALL SELECT * FROM fuelfinal
UNION ALL SELECT * FROM metafinal;
