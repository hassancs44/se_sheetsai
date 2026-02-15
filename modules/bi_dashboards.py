# SE_SHEETSAI — Optional BI dashboard config (slug-based).
# Used by /data-panel and nav. Native BI uses bi_models + DB (bi_dashboards table).

BI_DASHBOARDS = {
    "sales-demo": {
        "title": "Sales Demo Dashboard",
        "slug": "sales-demo",
        "default_params": {},
    },
    "ops-kpis": {
        "title": "Operations KPIs",
        "slug": "ops-kpis",
        "default_params": {},
    },
}


def get_bi_dashboard(slug):
    """Return config for slug or None."""
    return BI_DASHBOARDS.get(slug)


def list_bi_dashboards():
    """Return list of dashboard configs (for nav / data-panel)."""
    return list(BI_DASHBOARDS.values())
