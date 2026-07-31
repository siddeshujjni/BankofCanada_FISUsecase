# Genie Space — Bank of Canada Z4 Regulatory Returns

Scope the space to the governed **metric view** plus the metadata tables:
- `shm_catalog.metadata_db.mv_balance_sheet` (primary — clean business measures)
- `shm_catalog.metadata_db.time_series` (the decoder ring)
- `shm_catalog.metadata_db.financial_institutions` (the filers)

Create it programmatically (after the ingestion job builds the metric view):

```bash
DATABRICKS_CONFIG_PROFILE=fe-vm-shm-skunkworks \
  app/.venv/bin/python scripts/create_genie_space.py --create
```

Capture the printed **space_id** into `GENIE_SPACE_ID` (`app/app.yaml` and
`databricks.yml`), then redeploy so the app and grants pick it up.

## Semantic instructions (baked into the serialized space)
- Prefer the `mv_balance_sheet` metric view for quantitative questions; it exposes
  clean measures so raw cryptic datapoint codes are never summed.
- All monetary values are in **thousands of Canadian dollars**.
- The Big Six: RBC, TD, BNS, BMO, CIBC, NBC (`is_big6 = true`). Codes: OAB=RBC,
  OCB=TD, ODB=BNS, OEB=BMO, OFB=CIBC, OGB=NBC.
- "Latest"/"current" → the row with `MAX(obs_date)`. Reporting dates are month-ends.
- `loan_to_deposit_ratio = non_mortgage_loans / total_deposits`;
  `liquid_asset_ratio = (cash_and_equivalents + deposits_with_fis) / total_assets`.
  Never sum ratios across banks.
- A time-series name looks like `RZ4.OAB.V1045` = Return Z4 · FI OAB (RBC) ·
  datapoint V1045 (Total Assets); its lowercase metadata key adds a `#rrs` suffix.

## Sample questions to seed
- "Total assets of each of the Big Six in the latest Z4 filing."
- "Which Big Six bank has the highest loan-to-deposit ratio?"
- "Trend of RBC's cash and cash equivalents over the last 12 months."
