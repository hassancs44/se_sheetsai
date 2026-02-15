# Excel Links Schema Detection (Google Sheets-like UX)

## Overview

Excel Links now detects real business column headers from the master file, similar to Google Sheets. The system never silently falls back to system columns only when detection fails.

## How Detection Works

### `detect_master_headers(file_path, sheet_name, header_row_mode, max_scan_rows=10)`

- **header_row_mode**:
  - `"row1"`, `"row2"`, `"row3"` — Use that specific row
  - `"auto"` — Scan rows 1..max_scan_rows to find the first valid header row

- **Valid header row**:
  - At least 2 non-empty string header cells (configurable `min_business_cols`)
  - No duplicate header names after normalization
  - Not purely numeric junk
  - Not system columns only (`_row_uuid`, etc.)

- **Header extraction**:
  - Scans across columns 1..200 — does NOT stop at the first empty cell
  - Allows gaps; preserves left-to-right order
  - Normalizes: trim, collapse internal whitespace, remove invisible Unicode chars (Cf category, BOM, zero-width)

- **Return**: `{ ok, sheet_name, header_row_index, business_columns, system_columns, canonical_columns, preview_rows, warning }`

## Supported Header Modes

| Mode   | Behavior |
|--------|----------|
| `auto` | Scan rows 1–10; use first row with ≥2 non-duplicate business headers |
| `row1` | Use row 1 |
| `row2` | Use row 2 |
| `row3` | Use row 3 |

## Troubleshooting Missing Headers

1. **"No headers found"** — Put column names (e.g. `first_name`, `last_name`) in Row 1 (or Row 2/3). Select the correct sheet and header mode.

2. **A1 empty but B1 has header** — Detection scans all columns; gaps are allowed. If still failing, ensure ≥2 headers exist.

3. **Sheet1 empty** — Select the sheet that contains the data (e.g. Sheet2) in the dropdown.

4. **Only system columns shown** — Old links with empty `columns_json` are auto-refreshed on first open. If not, run **"Push schema to all children"**.

5. **Schema hash mismatch** — Master schema changed. Run **"Push schema to all children"** from the master file.

## API

- **GET** `/api/files/<file_id>/links/schema-preview?sheet_name=Sheet1&header_mode=auto`  
  Returns detected schema and preview rows. 400 if detection fails.

- **POST** `/api/files/<master_id>/links` — Requires valid schema. Returns 400 with clear message if headers not detectable.

## Backward Compatibility

- Existing links with empty or system-only `columns_json` are refreshed on first link-info load using auto-detect.
- `header_row_index` stored in `excel_link_schema`; default 1.
- Push-schema uses stored `header_row_index` when re-detecting.
