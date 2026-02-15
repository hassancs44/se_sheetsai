# SE_SHEETSAI — Security Model

## Permission Architecture

### Permission Types

1. **File/Folder Permissions**
   - `owner`: Full control (edit, delete, share, change permissions)
   - `editor`: Can edit content, cannot delete or change permissions
   - `viewer`: Read-only access

2. **Share Scope**
   - `user`: Specific user share
   - `department`: Department-wide share
   - `public`: Public share (optional, can be disabled)

3. **Fine-Grained Spreadsheet Permissions**
   - Sheet-level: Restrict access to specific sheets
   - Range-level: Restrict access to cell ranges (e.g., A1:K20)
   - Row-level / Column-level: Restrict entire rows/columns

4. **Policy Restrictions**
   - `allow_download`: Can download file
   - `allow_print`: Can print file
   - `allow_copy`: Can copy content
   - `allow_export`: Can export to other formats

### Permission Inheritance

- **Folder inheritance**: Child files/folders inherit parent folder permissions
- **Override**: Explicit permissions on child override inherited permissions
- **Expiry**: Permissions can have `expires_at` timestamp

## Data Model

### Core Tables

```sql
-- Users
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE,  -- Email
    password TEXT,         -- Hashed
    role TEXT,             -- System role (admin, user, etc.)
    department TEXT,
    apps TEXT,            -- CSV: drive,sheets,bi
    is_active INTEGER DEFAULT 1
);

-- Permissions
CREATE TABLE permissions (
    id INTEGER PRIMARY KEY,
    item_type TEXT,        -- 'file' or 'folder'
    item_id TEXT,
    target_type TEXT,      -- 'user', 'department', 'public'
    target_value TEXT,     -- User email or department name
    role TEXT,             -- 'owner', 'editor', 'viewer'
    expires_at TEXT,      -- ISO datetime or NULL
    created_at TEXT
);

-- Cell Permissions (fine-grained)
CREATE TABLE cell_permissions (
    id INTEGER PRIMARY KEY,
    file_id TEXT,
    principal_type TEXT,  -- 'user' or 'department'
    principal_value TEXT,
    sheet_name TEXT,
    range_a1 TEXT,        -- e.g., "A1:K20" or "1:10" (rows) or "A:Z" (cols)
    allow_edit INTEGER DEFAULT 1,
    created_at TEXT
);

-- Governance Policies (department-level)
CREATE TABLE governance_policies (
    id INTEGER PRIMARY KEY,
    department TEXT,
    allow_view INTEGER DEFAULT 1,
    allow_export INTEGER DEFAULT 0,
    allow_print INTEGER DEFAULT 0,
    allow_copy INTEGER DEFAULT 0,
    allow_refresh INTEGER DEFAULT 0,
    created_at TEXT,
    created_by TEXT
);

-- Audit Log
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    user TEXT,
    action TEXT,          -- 'file_viewed', 'file_edited', 'permission_granted', etc.
    resource_type TEXT,   -- 'file', 'folder', 'dashboard'
    resource_id TEXT,
    ip_address TEXT,
    user_agent TEXT,
    metadata TEXT,        -- JSON
    created_at TEXT
);
```

## Permission Enforcement

### Server-Side Enforcement (Mandatory)

All permission checks **must** be performed server-side:

1. **Route Protection**
   ```python
   @app.route("/file/<file_id>")
   @require_permission("file", "viewer")
   def view_file(file_id):
       # User has at least viewer permission
   ```

2. **OnlyOffice Edit Permission**
   - OnlyOffice config includes `permissions.edit` based on server check
   - Callback save validates user has edit permission
   - Cell-level edits validated against `cell_permissions` table

3. **Download/Print/Copy Restrictions**
   - UI buttons hidden if policy forbids
   - Backend routes return 403 if policy forbids
   - OnlyOffice config sets `permissions.download`, `permissions.print`, `permissions.copy`

4. **BI Dashboard Access**
   - `/bi/dashboard/<id>` checks `can_user_view_bi_dashboard()`
   - `/bi/studio/*` checks `can_access_bi()` + role permission
   - Metabase embed JWT includes user context (for future row-level security)

### Client-Side UI (Convenience Only)

UI controls are **convenience only** and must match server-side checks:

- Hide "Download" button if `allow_download = False`
- Hide "Edit" button if user role is `viewer`
- Show "Share" button only if user is `owner` or `editor`

## Role-Based Access Control (RBAC)

### System Roles

- `admin`: Full system access, can manage users, policies, audit
- `مدير عام`: General manager, can create BI dashboards, manage department
- `مدير القسم`: Department manager, can manage department files
- `تحليل البيانات`: Data analyst, can create BI dashboards
- `موظف`: Regular employee, viewer/editor based on shares

### App Access Control

Users have `apps` field (CSV): `drive,sheets,bi`

- If `bi` not in `apps`, BI routes return 403
- If `sheets` not in `apps`, sheet editor hidden

## BI Dashboard Permissions

### Dashboard Access Levels

1. **Owner**: Can edit dashboard, change permissions, delete
2. **Editor**: Can edit dashboard content, cannot change permissions
3. **Viewer**: Can view dashboard (read-only)

### Permission Storage

```sql
-- bi_dashboards table includes:
owner_user_id TEXT,
permissions_json TEXT,  -- JSON: {"users": [...], "departments": [...]}
```

### Enforcement

- `/bi/dashboard/<id>`: Checks `can_user_view_bi_dashboard()`
- `/bi/studio/dashboard/<id>`: Checks `can_user_edit_bi_dashboard()`
- Metabase embed JWT: Includes user ID (for future RLS)

## Audit & Compliance

### Audit Logging

Every action is logged:

- File view/edit/download
- Permission changes
- Dashboard access
- Policy violations
- Authentication events

### Audit Log Fields

- `user`: User email
- `action`: Action type (e.g., `file_viewed`, `permission_granted`)
- `resource_type`: `file`, `folder`, `dashboard`
- `resource_id`: ID of resource
- `ip_address`: Client IP
- `user_agent`: Browser/client info
- `metadata`: JSON with additional context
- `created_at`: Timestamp

### Compliance Features

- **Data Retention**: Audit logs retained per policy
- **Export**: Admin can export audit logs
- **Search**: Search audit logs by user, action, resource, date range

## Security Best Practices

1. **Never trust client**: All checks server-side
2. **JWT validation**: OnlyOffice callbacks validate JWT with leeway for time drift
3. **Password hashing**: Use bcrypt or similar (not plaintext)
4. **Session management**: Secure session cookies, timeout after inactivity
5. **HTTPS in production**: All traffic encrypted
6. **Rate limiting**: Prevent brute force attacks
7. **Input validation**: Sanitize all user inputs
8. **SQL injection prevention**: Use parameterized queries (already using `?` placeholders)

## Configuration

### .env Security Variables

```env
SECRET_KEY=<strong-random-secret>
ONLYOFFICE_JWT_SECRET=<strong-random-secret>
METABASE_SECRET_KEY=<strong-random-secret>
```

**Never commit `.env` to git.**

### Production Checklist

- [ ] Change all default secrets
- [ ] Use strong random secrets (32+ characters)
- [ ] Enable HTTPS
- [ ] Set secure session cookies (`Secure`, `HttpOnly`, `SameSite`)
- [ ] Configure firewall (only expose port 5000, not 3000)
- [ ] Regular security audits
- [ ] Monitor audit logs for anomalies

## Future Enhancements

- **Row-Level Security (RLS)**: Metabase RLS based on user context
- **Two-Factor Authentication (2FA)**: Optional 2FA for admin users
- **IP Whitelisting**: Restrict access by IP range
- **Data Loss Prevention (DLP)**: Scan files for sensitive data
- **Encryption at Rest**: Encrypt files on disk
