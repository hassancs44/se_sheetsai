import sqlite3
from config import DB_PATH

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    db = get_db()
    cur = db.cursor()

    # ===== Users =====
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        username TEXT UNIQUE,          -- البريد الالكتروني
        password TEXT,
        name TEXT,

        role TEXT,                     -- owner / editor / viewer
        department TEXT,
        extra_departments TEXT,        -- CSV: IT,HR,FIN

        company TEXT,
        branch TEXT,

        apps TEXT,                     -- CSV: drive,sheets,hr
        is_active INTEGER DEFAULT 1,
        force_reset INTEGER DEFAULT 0,

        failed_attempts INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)

    # ===== Sheets =====
    # ===== Folders =====
    cur.execute("""
    CREATE TABLE IF NOT EXISTS folders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        folder_id TEXT UNIQUE,
        name TEXT,
        owner TEXT,
        parent_id TEXT,
        is_trashed INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)

    # ===== Files =====
    cur.execute("""
    CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT UNIQUE,
    name TEXT,
    owner TEXT,
    folder_id TEXT,

    path TEXT,
    mime TEXT,
    file_type TEXT,          -- sheet | doc | slide | file

    is_trashed INTEGER DEFAULT 0,
    created_at TEXT
)

    """)
    # ===== Permissions =====
    cur.execute("""
    CREATE TABLE IF NOT EXISTS permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_type TEXT,        -- file | folder | sheet
        item_id TEXT,
        owner TEXT,            -- صاحب المشاركة
        target_type TEXT,      -- user | department | public
        target_value TEXT,     -- username | department_name | NULL
        role TEXT,             -- owner | editor | viewer
        created_at TEXT
    )
    """)

    # ===== Dashboards =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dashboards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dashboard_id TEXT UNIQUE,
            name TEXT,
            description TEXT,
            file_id TEXT,            -- file_id من جدول files (legacy)
            sheet_name TEXT DEFAULT 'Sheet1',
            department TEXT,
            owner TEXT,
            status TEXT DEFAULT 'draft',
            definition_json TEXT,
            created_at TEXT,
            updated_at TEXT,
            published_at TEXT,
            last_run_at TEXT,
            last_run_status TEXT
        )
        """)

    # ===== Dashboard KPIs =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dashboard_kpis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dashboard_id TEXT,
            label TEXT,
            column_name TEXT,
            agg TEXT,                -- sum | avg | count
            format TEXT,             -- number | currency | percent
            created_at TEXT
        )
        """)
    # ===== Dashboard Versions =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dashboard_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id TEXT UNIQUE,
            dashboard_id TEXT,
            created_by TEXT,
            created_at TEXT,
            reason TEXT,
            definition_json_snapshot TEXT
        )
    """)
    # ===== Datasets (optional) =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS datasets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id TEXT UNIQUE,
            name TEXT,
            owner TEXT,
            definition_json TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    # ===== Access Violations =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS access_violations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT,
            action TEXT,
            target_type TEXT,
            target_id TEXT,
            reason TEXT,
            created_at TEXT
        )
    """)

    # ===== Governance Policies =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS governance_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department TEXT,
            allow_view INTEGER DEFAULT 1,
            allow_export INTEGER DEFAULT 0,
            allow_print INTEGER DEFAULT 0,
            allow_copy INTEGER DEFAULT 0,
            allow_refresh INTEGER DEFAULT 0,
            created_at TEXT,
            created_by TEXT
        )
    """)

    db.commit()
    db.close()

import sqlite3
from config import DB_PATH, DB_FALLBACK_PATH

ACTIVE_DB_PATH = DB_PATH

def get_db():
    conn = sqlite3.connect(ACTIVE_DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

def _init_db(path):
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    cur = db.cursor()

    # ===== Users =====
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        username TEXT UNIQUE,          -- البريد الالكتروني
        password TEXT,
        name TEXT,

        role TEXT,                     -- owner / editor / viewer
        department TEXT,
        extra_departments TEXT,        -- CSV: IT,HR,FIN

        company TEXT,
        branch TEXT,

        apps TEXT,                     -- CSV: drive,sheets,hr
        is_active INTEGER DEFAULT 1,
        force_reset INTEGER DEFAULT 0,

        failed_attempts INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)

    # ===== Sheets =====
    # ===== Folders =====
    cur.execute("""
    CREATE TABLE IF NOT EXISTS folders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        folder_id TEXT UNIQUE,
        name TEXT,
        owner TEXT,
        parent_id TEXT,
        is_trashed INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)

    # ===== Files =====
    cur.execute("""
    CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT UNIQUE,
    name TEXT,
    owner TEXT,
    folder_id TEXT,

    path TEXT,
    mime TEXT,
    file_type TEXT,          -- sheet | doc | slide | file

    is_trashed INTEGER DEFAULT 0,
    created_at TEXT
)

    """)
    # ===== Permissions =====
    cur.execute("""
    CREATE TABLE IF NOT EXISTS permissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_type TEXT,        -- file | folder | sheet
        item_id TEXT,
        owner TEXT,            -- صاحب المشاركة
        target_type TEXT,      -- user | department | public
        target_value TEXT,     -- username | department_name | NULL
        role TEXT,             -- owner | editor | viewer
        created_at TEXT
    )
    """)

    # ===== Dashboards =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dashboards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dashboard_id TEXT UNIQUE,
            name TEXT,
            description TEXT,
            file_id TEXT,            -- file_id من جدول files (legacy)
            sheet_name TEXT DEFAULT 'Sheet1',
            department TEXT,
            owner TEXT,
            status TEXT DEFAULT 'draft',
            definition_json TEXT,
            created_at TEXT,
            updated_at TEXT,
            published_at TEXT,
            last_run_at TEXT,
            last_run_status TEXT
        )
        """)

    # ===== Dashboard KPIs =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dashboard_kpis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dashboard_id TEXT,
            label TEXT,
            column_name TEXT,
            agg TEXT,                -- sum | avg | count
            format TEXT,             -- number | currency | percent
            created_at TEXT
        )
        """)
    # ===== Dashboard Versions =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dashboard_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_id TEXT UNIQUE,
            dashboard_id TEXT,
            created_by TEXT,
            created_at TEXT,
            reason TEXT,
            definition_json_snapshot TEXT
        )
    """)
    # ===== Datasets (optional) =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS datasets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id TEXT UNIQUE,
            name TEXT,
            owner TEXT,
            definition_json TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)

    # ===== Cell/Row/Column/Range Permissions =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cell_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type TEXT,        -- file | folder
            item_id TEXT,
            target_type TEXT,      -- user | department | role | public
            target_value TEXT,
            sheet_name TEXT,
            scope_type TEXT,       -- cell | row | column | range
            scope_value TEXT,      -- B5 | 5 | B | B2:D200
            perm TEXT,             -- view | edit
            created_at TEXT,
            created_by TEXT
        )
    """)

    # ===== Versions =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS file_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT,
            version_no INTEGER,
            version_type TEXT,     -- autosave | daily | weekly | manual | pre_rollback | issued
            stored_path TEXT,
            hash TEXT,
            size_bytes INTEGER,
            created_at TEXT,
            created_by TEXT,
            notes TEXT
        )
    """)

    # ===== File participants (من فتح أو عدّل الملف) =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS file_participants (
            file_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY (file_id, user_id)
        )
    """)
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_file_participants_file ON file_participants (file_id)")
    except Exception:
        pass

    # ===== Audit Log =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            actor TEXT,
            actor_role TEXT,
            ip TEXT,
            user_agent TEXT,
            item_type TEXT,
            item_id TEXT,
            item_name TEXT,
            context_json TEXT,
            created_at TEXT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_log ON audit_log (item_type, item_id, created_at)")

    # ===== Automation Rules =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS automation_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            is_enabled INTEGER,
            priority INTEGER,
            trigger TEXT,
            conditions_json TEXT,
            actions_json TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """)

    # ===== Department Policies =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS department_policies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department TEXT,
            policy_json TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """)

    # ===== File Classification =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS file_classifications (
            file_id TEXT PRIMARY KEY,
            category TEXT,
            confidence REAL,
            method TEXT,
            rules_hit TEXT,
            updated_at TEXT,
            updated_by TEXT
        )
    """)

    # ===== Ownership Transfer =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ownership_transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type TEXT,
            item_id TEXT,
            from_owner TEXT,
            to_owner TEXT,
            include_children INTEGER,
            reason TEXT,
            signed_token TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """)

    # ===== BI Demo (Metabase analytics) =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bi_sales_demo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_date TEXT,
            branch TEXT,
            department TEXT,
            amount REAL,
            category TEXT
        )
    """)

    # ===== BI Dashboards (Metabase / Drive integration) =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bi_dashboards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            internal_id TEXT UNIQUE,
            title TEXT,
            metabase_dashboard_id INTEGER,
            linked_file_id TEXT,
            linked_folder_id TEXT,
            owner_user_id TEXT,
            allow_export INTEGER DEFAULT 0,
            allow_download INTEGER DEFAULT 0,
            allow_filter INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bi_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dashboard_id INTEGER,
            subject_type TEXT,
            subject_id TEXT,
            permission TEXT,
            expires_at TEXT,
            created_at TEXT,
            FOREIGN KEY (dashboard_id) REFERENCES bi_dashboards(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bi_datasets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            source_file_id TEXT,
            output_table_name TEXT,
            extract_mode TEXT DEFAULT 'full',
            last_sync_at TEXT,
            created_at TEXT,
            engine_type TEXT,            -- sqlite | postgres
            schema_json TEXT,            -- JSON: columns + types
            row_count INTEGER,
            ingestion_hash TEXT,
            last_ingested_at TEXT,
            status TEXT                  -- ready | stale | error
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bi_sync_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            internal_id TEXT,
            file_id TEXT,
            triggered_by TEXT,
            started_at TEXT,
            finished_at TEXT,
            status TEXT,
            row_count INTEGER,
            error_message TEXT,
            created_at TEXT
        )
    """)

    # ===== Excel Link (Master/Child aggregation) =====
    cur.execute("""
        CREATE TABLE IF NOT EXISTS file_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_file_id TEXT NOT NULL,
            child_file_id TEXT NOT NULL,
            child_owner_user_id TEXT,
            child_owner_email TEXT,
            link_status TEXT DEFAULT 'active',
            created_at TEXT,
            updated_at TEXT,
            UNIQUE(master_file_id, child_file_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS excel_link_schema (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_file_id TEXT NOT NULL UNIQUE,
            sheet_name TEXT DEFAULT 'Sheet1',
            columns_json TEXT,
            row_uuid_column_name TEXT DEFAULT '_row_uuid',
            source_child_column_name TEXT DEFAULT '_source_child_file_id',
            source_user_column_name TEXT DEFAULT '_source_user_id',
            created_at TEXT,
            updated_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS excel_link_sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            master_file_id TEXT NOT NULL,
            child_file_id TEXT NOT NULL,
            status TEXT,
            rows_inserted INTEGER DEFAULT 0,
            rows_updated INTEGER DEFAULT 0,
            rows_deleted INTEGER DEFAULT 0,
            error_message TEXT,
            synced_at TEXT
        )
    """)
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_file_links_child ON file_links (child_file_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_file_links_master ON file_links (master_file_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_excel_link_sync_log_master ON excel_link_sync_log (master_file_id)")
    except Exception:
        pass

    # ===== Search Index (FTS5) =====
    try:
        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
                item_type,
                item_id,
                title,
                content,
                tags,
                department,
                updated_by,
                updated_at
            )
        """)
    except Exception:
        # FTS5 might be unavailable in some SQLite builds
        pass

    # ===== Schema Updates (safe ALTER) =====
    def safe_add_column(table, col_def):
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
        except Exception:
            pass

    safe_add_column("permissions", "expires_at TEXT")
    safe_add_column("files", "last_opened_at TEXT")
    safe_add_column("files", "archived_at TEXT")
    safe_add_column("files", "compressed_at TEXT")
    safe_add_column("files", "updated_at TEXT")
    safe_add_column("cell_permissions", "item_type TEXT")
    safe_add_column("cell_permissions", "item_id TEXT")
    safe_add_column("cell_permissions", "perm TEXT")
    safe_add_column("cell_permissions", "created_by TEXT")
    safe_add_column("file_versions", "version_no INTEGER")
    safe_add_column("file_versions", "version_type TEXT")
    safe_add_column("file_versions", "stored_path TEXT")
    safe_add_column("file_versions", "hash TEXT")
    safe_add_column("file_versions", "size_bytes INTEGER")
    safe_add_column("file_versions", "notes TEXT")
    safe_add_column("audit_log", "event_type TEXT")
    safe_add_column("audit_log", "actor_role TEXT")
    safe_add_column("audit_log", "ip TEXT")
    safe_add_column("audit_log", "user_agent TEXT")
    safe_add_column("audit_log", "item_name TEXT")
    safe_add_column("audit_log", "context_json TEXT")
    safe_add_column("automation_rules", "is_enabled INTEGER")
    safe_add_column("automation_rules", "priority INTEGER")
    safe_add_column("automation_rules", "conditions_json TEXT")
    safe_add_column("automation_rules", "actions_json TEXT")
    safe_add_column("automation_rules", "created_by TEXT")
    safe_add_column("department_policies", "policy_json TEXT")
    safe_add_column("department_policies", "created_by TEXT")
    safe_add_column("file_classifications", "category TEXT")
    safe_add_column("file_classifications", "method TEXT")
    safe_add_column("file_classifications", "rules_hit TEXT")
    safe_add_column("file_classifications", "updated_at TEXT")
    safe_add_column("file_classifications", "updated_by TEXT")
    safe_add_column("ownership_transfers", "from_owner TEXT")
    safe_add_column("ownership_transfers", "to_owner TEXT")
    safe_add_column("ownership_transfers", "include_children INTEGER")
    safe_add_column("ownership_transfers", "reason TEXT")
    safe_add_column("ownership_transfers", "signed_token TEXT")
    safe_add_column("ownership_transfers", "created_by TEXT")
    safe_add_column("dashboards", "owner TEXT")
    safe_add_column("dashboards", "status TEXT")
    safe_add_column("dashboards", "definition_json TEXT")
    safe_add_column("dashboards", "updated_at TEXT")
    safe_add_column("dashboards", "published_at TEXT")
    safe_add_column("dashboards", "last_run_at TEXT")
    safe_add_column("dashboards", "last_run_status TEXT")
    # BI: evolve legacy Metabase-backed schema into native BI engine schema.
    safe_add_column("bi_datasets", "engine_type TEXT")
    safe_add_column("bi_datasets", "schema_json TEXT")
    safe_add_column("bi_datasets", "row_count INTEGER")
    safe_add_column("bi_datasets", "ingestion_hash TEXT")
    safe_add_column("bi_datasets", "last_ingested_at TEXT")
    safe_add_column("bi_datasets", "status TEXT")
    safe_add_column("bi_dashboards", "metabase_collection_id INTEGER")
    safe_add_column("bi_dashboards", "metabase_database_id INTEGER")
    safe_add_column("bi_dashboards", "dataset_key TEXT")
    safe_add_column("bi_dashboards", "updated_at TEXT")
    safe_add_column("bi_dashboards", "visibility_level TEXT")  # private | department | company
    safe_add_column("bi_dashboards", "layout_json TEXT")
    safe_add_column("bi_dashboards", "filters_json TEXT")
    safe_add_column("bi_dashboards", "status TEXT")        # draft | published | archived
    safe_add_column("bi_dashboards", "needs_refresh INTEGER DEFAULT 0")
    safe_add_column("bi_dashboards", "theme_json TEXT")    # { "mode": "light"|"dark", "primary": "#...", ... }
    safe_add_column("bi_widgets", "interaction_json TEXT")  # { "drill": { "enabled": true, "target": "modal" }, "crossFilter": true }
    safe_add_column("excel_link_schema", "last_synced_at_column_name TEXT DEFAULT '_last_synced_at'")
    safe_add_column("excel_link_schema", "sync_mode TEXT DEFAULT 'append'")  # append | upsert (SSOT: append-only to master)
    safe_add_column("excel_link_schema", "row_locked_at_column_name TEXT DEFAULT '_row_locked_at'")
    safe_add_column("excel_link_schema", "schema_hash TEXT")  # SHA256 of canonical schema for governance
    safe_add_column("excel_link_schema", "header_row_index INTEGER DEFAULT 1")  # 1/2/3; row containing headers
    safe_add_column("excel_link_sync_log", "version_no INTEGER")
    # Enterprise: immutable child rows after first sync
    cur.execute("""
        CREATE TABLE IF NOT EXISTS synced_row_locks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            child_file_id TEXT NOT NULL,
            row_uuid TEXT NOT NULL,
            row_content_hash TEXT NOT NULL,
            locked_at TEXT NOT NULL,
            UNIQUE(child_file_id, row_uuid)
        )
    """)
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_synced_row_locks_child ON synced_row_locks (child_file_id)")
    except Exception:
        pass

    # Native BI widgets table (separate from legacy dashboards table)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bi_widgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            widget_id TEXT,
            dashboard_internal_id TEXT,
            type TEXT,
            title TEXT,
            query_json TEXT,
            config_json TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bi_dashboard_filters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dashboard_internal_id TEXT NOT NULL,
            filter_key TEXT NOT NULL,
            filter_type TEXT,
            label TEXT,
            config_json TEXT,
            created_at TEXT
        )
    """)
    try:
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_bi_dashboard_filters_dash_key ON bi_dashboard_filters (dashboard_internal_id, filter_key)")
    except Exception:
        pass

    cur.execute("""
        CREATE TABLE IF NOT EXISTS bi_dashboard_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            layout_json TEXT,
            widgets_json TEXT,
            theme_json TEXT,
            created_at TEXT,
            created_by TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bi_dashboard_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dashboard_internal_id TEXT NOT NULL,
            layout_json TEXT,
            widgets_json TEXT,
            version_no INTEGER DEFAULT 1,
            created_at TEXT,
            created_by TEXT
        )
    """)
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_bi_dashboard_versions_dash ON bi_dashboard_versions (dashboard_internal_id)")
    except Exception:
        pass

    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_cell_permissions ON cell_permissions (item_id, sheet_name, target_type, target_value)")
    except Exception:
        pass
    try:
        cur.execute("CREATE INDEX IF NOT EXISTS idx_file_versions ON file_versions (file_id, version_no)")
    except Exception:
        pass

    db.commit()
    db.close()

def init_db():
    global ACTIVE_DB_PATH
    try:
        _init_db(ACTIVE_DB_PATH)
    except sqlite3.OperationalError as e:
        if "disk i/o" in str(e).lower():
            ACTIVE_DB_PATH = DB_FALLBACK_PATH
            _init_db(ACTIVE_DB_PATH)
        else:
            raise

def use_fallback_db():
    global ACTIVE_DB_PATH
    ACTIVE_DB_PATH = DB_FALLBACK_PATH

