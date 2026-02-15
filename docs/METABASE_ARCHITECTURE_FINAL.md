# Metabase Integration — Final Production Architecture

## ✅ Architecture Overview

**Option A: Direct Metabase URLs with Signed JWT Embedding**

- **Viewer Mode**: Uses signed JWT tokens to embed dashboards directly from Metabase (`http://127.0.0.1:3000/embed/dashboard/<jwt>`)
- **Studio Mode**: Redirects directly to Metabase (`http://127.0.0.1:3000/#/dashboard/<id>`) for editing
- **No Proxy**: Eliminated fragile subpath proxy and HTML/JS rewriting
- **No Iframe Issues**: Cross-origin embedding works because Metabase's `/embed/` endpoint is designed for iframes

## 🔧 Configuration

### docker-compose.yml

```yaml
metabase:
  environment:
    MB_SITE_URL: http://127.0.0.1:3000  # Direct Metabase URL (no subpath)
    MB_EMBEDDING_APP_ORIGIN: http://127.0.0.1:5000  # Flask app origin
    MB_SESSION_COOKIE_SAMESITE: None
    MB_SESSION_COOKIE_SECURE: "false"
    MB_ENABLE_EMBEDDING: "true"
    # For Metabase 0.51+ (replaces deprecated MB_ENABLE_EMBEDDING)
    MB_EMBEDDING_APP_ORIGINS_SDK: http://127.0.0.1:5000
    MB_EMBEDDING_APP_ORIGINS_INTERACTIVE: http://127.0.0.1:5000
```

### .env

```bash
METABASE_BASE_URL=http://127.0.0.1:3000
METABASE_SITE_URL=http://127.0.0.1:3000
METABASE_SECRET_KEY=your_secret_key_here
```

**Important**: `METABASE_SECRET_KEY` must match `MB_EMBEDDING_APP_SECRET` in Metabase Admin → Settings → Embedding.

## 📋 Routes

### Viewer (Signed JWT Embed)

- **Route**: `GET /bi/dashboard/<internal_id>`
- **Method**: Generates signed JWT, embeds dashboard in iframe
- **URL**: `http://127.0.0.1:3000/embed/dashboard/<jwt>`
- **No Proxy**: Direct iframe to Metabase (cross-origin, but Metabase supports this)

### Studio (Direct Redirect)

- **Route**: `GET /bi/studio/new` → Redirects to `http://127.0.0.1:3000/#/dashboard/new`
- **Route**: `GET /bi/studio/dashboard/<internal_id>` → Redirects to `http://127.0.0.1:3000/#/dashboard/<metabase_id>`
- **No Iframe**: Opens Metabase directly in same tab
- **No SSO**: Users log into Metabase separately (or configure SSO separately)

## 🚀 Deployment Steps

1. **Update docker-compose.yml** (already done)
   ```bash
   docker compose down
   docker compose up -d
   ```

2. **Update .env** (if needed)
   ```bash
   METABASE_BASE_URL=http://127.0.0.1:3000
   METABASE_SITE_URL=http://127.0.0.1:3000
   ```

3. **Restart Metabase** to pick up new `MB_SITE_URL`
   ```bash
   docker compose restart metabase
   ```

4. **Configure Metabase Embedding**
   - Admin → Settings → Embedding
   - Enable "Signed Embedding"
   - Set secret = `METABASE_SECRET_KEY` from `.env`

5. **Restart Flask** (or rely on debugger auto-reload)

6. **Test**
   - Viewer: `/bi/dashboard/<id>` → Dashboard loads in iframe ✅
   - Studio: `/bi/studio/new` → Redirects to Metabase ✅

## 🔍 What Was Removed

- ❌ `/metabase/` proxy routes
- ❌ HTML rewriting (`_rewrite_metabase_html`)
- ❌ JS rewriting (`_rewrite_metabase_js`)
- ❌ Base tag injection
- ❌ Same-origin cookie forwarding
- ❌ SSO session management for Studio (no longer needed)

## ✅ Benefits

1. **Reliability**: No fragile HTML/JS rewriting
2. **Simplicity**: Direct URLs, no proxy complexity
3. **Performance**: No proxy overhead
4. **Maintainability**: Standard Metabase embedding pattern
5. **Zero Blank Iframes**: Metabase's `/embed/` endpoint is designed for cross-origin iframes

## 🔐 Security Notes

- Signed JWT tokens expire after 10 minutes (configurable)
- Embedding secret must match between Flask and Metabase
- Studio editing requires separate Metabase login (or configure SSO separately)
- Cross-origin iframe embedding is secure because Metabase validates the JWT signature

## 📝 Troubleshooting

### Dashboard shows blank
- Check `METABASE_SECRET_KEY` matches Metabase embedding secret
- Check Metabase Admin → Settings → Embedding is enabled
- Check browser console for errors (CORS, JWT validation, etc.)

### Studio redirect doesn't work
- Check `METABASE_BASE_URL` is correct (`http://127.0.0.1:3000`)
- Check Metabase container is running (`docker ps`)
- Check Metabase is accessible (`curl http://127.0.0.1:3000/api/health`)

### JWT validation fails
- Ensure `METABASE_SECRET_KEY` matches Metabase embedding secret exactly
- Check token expiration (default 10 minutes)
- Check Metabase logs for JWT validation errors

## 🎯 Production Considerations

For production with HTTPS:

1. Update `MB_SITE_URL` to production URL: `https://metabase.example.com`
2. Update `MB_EMBEDDING_APP_ORIGIN` to Flask app URL: `https://app.example.com`
3. Set `MB_SESSION_COOKIE_SECURE: "true"` (requires HTTPS)
4. Use strong `METABASE_SECRET_KEY` (32+ random characters)
