# Genie Space — Bank of Canada public data

Created in Task #5. Scope the space to `shm_catalog.boc_demo.boc_rates` (optionally
`market_prices`). Capture the resulting **space_id** into `GENIE_SPACE_ID`
(`.env` locally and `app/app.yaml` for deploy).

## Semantic instructions (paste into the space)
- All rate values are in **percent** unless the `unit` column says otherwise.
- `FXUSDCAD` is **CAD per USD** (the USD→CAD exchange rate).
- The **policy / overnight target rate** is series `V39079`.
- Central measures: policy rate, bond yields, CPI/inflation. Dimensions:
  `series_id` / `series_label` and `obs_date`.
- For "latest" questions use the **max `obs_date`** per series.
- Fiscal-year aggregations run **April 1 – March 31** (Government of Canada FY).
- "Change over time" = difference between the value at two `obs_date`s for one series.

## Sample SQL to seed the space
```sql
-- Latest overnight target rate
SELECT obs_date, value
FROM shm_catalog.boc_demo.boc_rates
WHERE series_id = 'V39079'
ORDER BY obs_date DESC LIMIT 1;

-- CPI trend over the last 12 observations
SELECT obs_date, value
FROM shm_catalog.boc_demo.boc_rates
WHERE series_label ILIKE '%CPI%'
ORDER BY obs_date DESC LIMIT 12;
```

## Creation
Genie spaces are created in the workspace UI (Genie > New space) or via the
SDK/REST. Record the space_id here once created:

```
GENIE_SPACE_ID = <fill-me-in>
```
