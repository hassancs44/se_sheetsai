# BI Query Schema (Official)

This document defines the canonical structure for `query_json` used by widgets and the `/bi/query` API.

## Canonical Structure

```json
{
  "dataset": "string",
  "dimensions": ["column_name"],
  "measures": [
    { "column": "col", "agg": "sum" }
  ],
  "filters": [
    { "column": "col", "op": "eq", "value": "x" }
  ],
  "sort": [
    { "field": "column_or_alias", "direction": "asc" }
  ],
  "limit": 1000
}
```

## Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `dataset` | string | Yes | Dataset/table name (e.g. `dataset_file123_sheet0`). Aliased as `table` in code. |
| `dimensions` | string[] | No | Column names for grouping/labels. Must exist in dataset schema. |
| `measures` | object[] | No | Aggregations. Each: `column` (or `field`), `agg`. |
| `filters` | object[] | No | Filter clauses. Each: `column` (or `field`), `op`, `value`. |
| `sort` | object[] | No | Sort. Each: `field`, `direction` (`asc` \| `desc`). |
| `limit` | number | No | Max rows (default 500). **Max allowed: 5000.** |

## Aggregations

Allowed values for `measures[].agg`:

- `sum`
- `avg`
- `count`
- `min`
- `max`

## Filter Operators

Allowed values for `filters[].op`:

| Op | Description | `value` shape |
|----|-------------|----------------|
| `eq` or `=` | Equals | scalar |
| `ne` or `!=` | Not equals | scalar |
| `gt` | Greater than | scalar |
| `lt` | Less than | scalar |
| `gte` | Greater or equal | scalar |
| `lte` | Less or equal | scalar |
| `between` | Between (inclusive) | `[low, high]` |
| `in` | In list | array |
| `contains` / `like` | Contains (string) | scalar |

## Validation

- All dimensions, measures, and filter columns **must exist** in the dataset schema.
- Validation is performed by `modules/bi_validation.validate_query_json(query_json, dataset_schema)` before execution.
- Invalid queries return HTTP 400 with a clear error message.

## Example

```json
{
  "dataset": "dataset_file45_sheet0",
  "dimensions": ["region"],
  "measures": [
    { "column": "sales", "agg": "sum" }
  ],
  "filters": [
    { "column": "date", "op": "between", "value": ["2025-01-01", "2025-12-31"] }
  ],
  "sort": [{ "field": "sales_sum", "direction": "desc" }],
  "limit": 1000
}
```
