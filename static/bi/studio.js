/**
 * SE_SHEETSAI — Native BI Studio: grid layout, add widgets, Style/Data/Interaction tabs, save.
 * Widget selection: click grid item to edit query/config/interaction; panel changes sync to widgets array.
 */
(function() {
  'use strict';

  var dashboardId = null;
  var widgets = [];
  var datasets = [];
  var saveUrl = null;
  var layoutItems = {};
  var selectedWidgetId = null;

  function parseJson(val, fallback) {
    if (val == null) return fallback != null ? fallback : {};
    if (typeof val === 'object') return val;
    try { return JSON.parse(val); } catch (e) { return fallback != null ? fallback : {}; }
  }

  function getSchemaColumns(datasetId) {
    var ds = datasets.find(function(d) {
      var name = d.output_table_name || d.table_name || '';
      return name === datasetId;
    });
    if (!ds) return [];
    var schema = parseJson(ds.schema_json, {});
    var cols = schema.columns || schema || [];
    if (Array.isArray(cols)) return cols;
    return Object.keys(cols);
  }

  function init(opts) {
    dashboardId = opts.dashboardId;
    widgets = (opts.widgets || []).map(function(w) {
      return {
        widget_id: w.widget_id || w.id,
        type: w.type || 'kpi',
        title: w.title || '',
        query: parseJson(w.query || w.query_json, { table: '', dimensions: [], measures: [], filters: [], limit: 100 }),
        config: parseJson(w.config || w.config_json, {}),
        interaction: parseJson(w.interaction_json, {})
      };
    });
    datasets = opts.datasets || [];
    saveUrl = opts.saveUrl || '';

    var saveBtn = document.getElementById('bi-studio-save');
    if (saveBtn) saveBtn.addEventListener('click', save);

    var addBtn = document.getElementById('bi-add-widget');
    if (addBtn) addBtn.addEventListener('click', addWidget);

    var themePreset = document.getElementById('bi-theme-preset');
    if (themePreset) {
      fetch('/static/bi/themes.json').then(function(r) { return r.json(); }).then(function(data) {
        var presets = (data && data.presets) || [];
        presets.forEach(function(p) {
          var opt = document.createElement('option');
          opt.value = p.id || p.mode;
          opt.textContent = p.name || p.id;
          themePreset.appendChild(opt);
        });
      }).catch(function() {});
      themePreset.addEventListener('change', function() {
        var val = themePreset.value;
        if (!val) return;
        fetch('/static/bi/themes.json').then(function(r) { return r.json(); }).then(function(data) {
          var presets = (data && data.presets) || [];
          var p = presets.find(function(x) { return (x.id || x.mode) === val; });
          if (p && p.mode) {
            var modeEl = document.getElementById('bi-theme-mode');
            if (modeEl) modeEl.value = p.mode;
          }
        }).catch(function() {});
      });
    }

    var templateName = document.getElementById('bi-template-name');
    var saveTemplateBtn = document.getElementById('bi-save-template-btn');
    if (saveTemplateBtn) {
      saveTemplateBtn.addEventListener('click', function() {
        var name = (templateName && templateName.value) || 'Template';
        if (!name.trim()) { alert('أدخل اسم القالب'); return; }
        fetch(opts.templateSaveUrl || '/bi/template/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dashboard_id: dashboardId, name: name.trim() })
        }).then(function(r) { return r.json(); }).then(function(d) {
          if (d.ok) alert('تم حفظ القالب.'); else alert(d.error || 'فشل');
        }).catch(function() { alert('فشل'); });
      });
    }

    function loadVersions() {
      var url = opts.versionsUrl || ('/bi/dashboard/' + dashboardId + '/versions');
      fetch(url).then(function(r) { return r.json(); }).then(function(d) {
        var sel = document.getElementById('bi-version-select');
        if (!sel) return;
        sel.innerHTML = '<option value="">— اختر إصدارًا للعودة —</option>';
        (d.versions || []).forEach(function(v) {
          var opt = document.createElement('option');
          opt.value = v.id;
          opt.textContent = 'إصدار ' + (v.version_no || v.id) + ' - ' + (v.created_at || '');
          sel.appendChild(opt);
        });
      }).catch(function() {});
    }
    loadVersions();
    var rollbackBtn = document.getElementById('bi-rollback-btn');
    if (rollbackBtn) {
      rollbackBtn.addEventListener('click', function() {
        var sel = document.getElementById('bi-version-select');
        var vid = sel && sel.value;
        if (!vid) { alert('اختر إصدارًا'); return; }
        var url = opts.rollbackUrl || ('/bi/dashboard/' + dashboardId + '/rollback');
        fetch(url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ version_id: parseInt(vid, 10) })
        }).then(function(r) { return r.json(); }).then(function(d) {
          if (d.ok) { alert('تمت الاستعادة.'); window.location.reload(); } else alert(d.error || 'فشل');
        }).catch(function() { alert('فشل'); });
      });
    }

    var datasetSelect = document.getElementById('bi-dataset-select');
    if (datasetSelect) {
      datasetSelect.addEventListener('change', function() {
        fillColumnSelects(datasetSelect.value);
        applyDataToSelectedWidget();
      });
    }

    var dimensionSelect = document.getElementById('bi-query-dimension');
    var measureColSelect = document.getElementById('bi-query-measure-col');
    var measureAggSelect = document.getElementById('bi-query-measure-agg');
    var limitInput = document.getElementById('bi-query-limit');
    if (dimensionSelect) dimensionSelect.addEventListener('change', applyDataToSelectedWidget);
    if (measureColSelect) measureColSelect.addEventListener('change', applyDataToSelectedWidget);
    if (measureAggSelect) measureAggSelect.addEventListener('change', applyDataToSelectedWidget);
    if (limitInput) limitInput.addEventListener('input', applyDataToSelectedWidget);

    var stylePrimary = document.getElementById('bi-style-primary');
    var styleColors = document.getElementById('bi-style-colors');
    var styleRadius = document.getElementById('bi-style-radius');
    var styleFont = document.getElementById('bi-style-font');
    var styleGradient = document.getElementById('bi-style-gradient');
    var styleShadow = document.getElementById('bi-style-shadow');
    var styleLegend = document.getElementById('bi-style-legend');
    [stylePrimary, styleColors, styleRadius, styleFont, styleGradient, styleShadow, styleLegend].forEach(function(el) {
      if (el) el.addEventListener('change', applyStyleToSelectedWidget);
      if (el && el.type === 'text') el.addEventListener('input', applyStyleToSelectedWidget);
    });

    var interactionDrill = document.getElementById('bi-interaction-drill');
    var interactionCross = document.getElementById('bi-interaction-crossfilter');
    var interactionRefresh = document.getElementById('bi-interaction-refresh');
    [interactionDrill, interactionCross, interactionRefresh].forEach(function(el) {
      if (el) el.addEventListener('change', applyInteractionToSelectedWidget);
    });

    // Panel tabs
    var tabs = document.querySelectorAll('.bi-studio-panel-tab');
    tabs.forEach(function(tab) {
      tab.addEventListener('click', function() {
        var t = tab.getAttribute('data-tab');
        tabs.forEach(function(x) { x.classList.remove('active'); });
        tab.classList.add('active');
        document.querySelectorAll('.bi-panel-content').forEach(function(panel) {
          panel.style.display = 'none';
        });
        var panel = document.getElementById('bi-panel-' + t);
        if (panel) panel.style.display = 'block';
      });
    });

    // Grid item click: select widget and fill panels
    var grid = document.getElementById('bi-studio-grid');
    if (grid) {
      grid.addEventListener('click', function(e) {
        var item = e.target.closest('.bi-grid-item[data-widget-id]');
        if (item) selectWidget(item.getAttribute('data-widget-id'));
      });
    }

    fillColumnSelects(datasetSelect && datasetSelect.value ? datasetSelect.value : (datasets[0] && (datasets[0].output_table_name || datasets[0].table_name)));
    if (widgets.length) selectWidget(widgets[0].widget_id);
  }

  function fillColumnSelects(tableId) {
    var cols = getSchemaColumns(tableId || '');
    var dimensionSelect = document.getElementById('bi-query-dimension');
    var measureColSelect = document.getElementById('bi-query-measure-col');
    function fillSelect(sel, allowEmpty) {
      if (!sel) return;
      var cur = sel.value;
      sel.innerHTML = allowEmpty ? '<option value="">— اختر العمود —</option>' : '';
      cols.forEach(function(c) {
        var name = typeof c === 'string' ? c : (c.name || c);
        var opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        sel.appendChild(opt);
      });
      if (allowEmpty && cur && cols.indexOf(cur) >= 0) sel.value = cur;
      else if (!allowEmpty && cur && cols.indexOf(cur) >= 0) sel.value = cur;
    }
    fillSelect(dimensionSelect, true);
    fillSelect(measureColSelect, true);
  }

  function selectWidget(widgetId) {
    selectedWidgetId = widgetId;
    var widget = widgets.find(function(w) { return (w.widget_id || w.id) === widgetId; });
    var showWidgetPanel = !!widget;
    document.querySelectorAll('.bi-panel-widget-style').forEach(function(el) { el.style.display = showWidgetPanel ? 'block' : 'none'; });
    document.querySelectorAll('.bi-no-widget-msg').forEach(function(el) { el.style.display = showWidgetPanel ? 'none' : 'block'; });

    document.querySelectorAll('#bi-studio-grid .bi-grid-item').forEach(function(el) {
      el.classList.toggle('bi-widget-selected', el.getAttribute('data-widget-id') === widgetId);
    });

    if (!widget) return;

    var q = widget.query || {};
    var table = q.table || q.dataset || '';
    var datasetSelect = document.getElementById('bi-dataset-select');
    if (datasetSelect) datasetSelect.value = table;
    fillColumnSelects(table);

    var dim = (q.dimensions && q.dimensions[0]) || '';
    var measure = (q.measures && q.measures[0]) ? (q.measures[0].column || q.measures[0].field) : '';
    var agg = (q.measures && q.measures[0]) ? (q.measures[0].agg || 'sum') : 'sum';
    var dimensionSelect = document.getElementById('bi-query-dimension');
    var measureColSelect = document.getElementById('bi-query-measure-col');
    var measureAggSelect = document.getElementById('bi-query-measure-agg');
    var limitInput = document.getElementById('bi-query-limit');
    if (dimensionSelect) dimensionSelect.value = dim;
    if (measureColSelect) measureColSelect.value = measure;
    if (measureAggSelect) measureAggSelect.value = agg;
    if (limitInput) limitInput.value = q.limit != null ? q.limit : 100;

    var cfg = widget.config || {};
    var stylePrimary = document.getElementById('bi-style-primary');
    var styleColors = document.getElementById('bi-style-colors');
    var styleRadius = document.getElementById('bi-style-radius');
    var styleFont = document.getElementById('bi-style-font');
    var styleGradient = document.getElementById('bi-style-gradient');
    var styleShadow = document.getElementById('bi-style-shadow');
    var styleLegend = document.getElementById('bi-style-legend');
    if (stylePrimary) stylePrimary.value = cfg.primary || cfg.backgroundColor || '#2563eb';
    if (styleColors) styleColors.value = (cfg.colors || []).join(', ');
    if (styleRadius) styleRadius.value = cfg.borderRadius != null ? cfg.borderRadius : 8;
    if (styleFont) styleFont.value = cfg.fontFamily || '';
    if (styleGradient) styleGradient.checked = cfg.gradient === true;
    if (styleShadow) styleShadow.checked = cfg.shadow === true;
    if (styleLegend) styleLegend.checked = cfg.showLegend !== false;

    var inter = widget.interaction || {};
    var interactionDrill = document.getElementById('bi-interaction-drill');
    var interactionCross = document.getElementById('bi-interaction-crossfilter');
    var interactionRefresh = document.getElementById('bi-interaction-refresh');
    if (interactionDrill) interactionDrill.checked = !!(inter.drill && inter.drill.enabled);
    if (interactionCross) interactionCross.checked = !!inter.crossFilter;
    if (interactionRefresh) interactionRefresh.value = inter.autoRefreshSeconds || 0;
  }

  function applyDataToSelectedWidget() {
    if (!selectedWidgetId) return;
    var w = widgets.find(function(x) { return (x.widget_id || x.id) === selectedWidgetId; });
    if (!w) return;
    var datasetSelect = document.getElementById('bi-dataset-select');
    var dimensionSelect = document.getElementById('bi-query-dimension');
    var measureColSelect = document.getElementById('bi-query-measure-col');
    var measureAggSelect = document.getElementById('bi-query-measure-agg');
    var limitInput = document.getElementById('bi-query-limit');
    w.query = w.query || {};
    w.query.table = w.query.dataset = (datasetSelect && datasetSelect.value) || '';
    w.query.dimensions = (dimensionSelect && dimensionSelect.value) ? [dimensionSelect.value] : [];
    var col = (measureColSelect && measureColSelect.value) || (dimensionSelect && dimensionSelect.value);
    w.query.measures = [{ column: col, field: col, agg: (measureAggSelect && measureAggSelect.value) || 'sum' }];
    w.query.limit = limitInput ? parseInt(limitInput.value, 10) || 100 : 100;
  }

  function applyStyleToSelectedWidget() {
    if (!selectedWidgetId) return;
    var w = widgets.find(function(x) { return (x.widget_id || x.id) === selectedWidgetId; });
    if (!w) return;
    w.config = w.config || {};
    var stylePrimary = document.getElementById('bi-style-primary');
    var styleColors = document.getElementById('bi-style-colors');
    var styleRadius = document.getElementById('bi-style-radius');
    var styleFont = document.getElementById('bi-style-font');
    var styleGradient = document.getElementById('bi-style-gradient');
    var styleShadow = document.getElementById('bi-style-shadow');
    var styleLegend = document.getElementById('bi-style-legend');
    if (stylePrimary) w.config.backgroundColor = w.config.primary = stylePrimary.value;
    if (styleColors) {
      w.config.colors = styleColors.value.split(',').map(function(s) { return s.trim(); }).filter(Boolean);
    }
    if (styleRadius) w.config.borderRadius = parseInt(styleRadius.value, 10) || 0;
    if (styleFont) w.config.fontFamily = styleFont.value || undefined;
    w.config.gradient = styleGradient && styleGradient.checked;
    w.config.shadow = styleShadow && styleShadow.checked;
    w.config.showLegend = !(styleLegend && !styleLegend.checked);
  }

  function applyInteractionToSelectedWidget() {
    if (!selectedWidgetId) return;
    var w = widgets.find(function(x) { return (x.widget_id || x.id) === selectedWidgetId; });
    if (!w) return;
    w.interaction = w.interaction || {};
    var interactionDrill = document.getElementById('bi-interaction-drill');
    var interactionCross = document.getElementById('bi-interaction-crossfilter');
    var interactionRefresh = document.getElementById('bi-interaction-refresh');
    w.interaction.drill = { enabled: !!(interactionDrill && interactionDrill.checked), target: 'modal' };
    w.interaction.crossFilter = !!(interactionCross && interactionCross.checked);
    w.interaction.autoRefreshSeconds = interactionRefresh ? parseInt(interactionRefresh.value, 10) || 0 : 0;
  }

  function addWidget() {
    var tableSelect = document.getElementById('bi-dataset-select');
    var titleInput = document.getElementById('bi-widget-title');
    var typeSelect = document.getElementById('bi-widget-type');
    var dimensionSelect = document.getElementById('bi-query-dimension');
    var measureColSelect = document.getElementById('bi-query-measure-col');
    var measureAggSelect = document.getElementById('bi-query-measure-agg');
    var limitInput = document.getElementById('bi-query-limit');

    var table = (tableSelect && tableSelect.value) || (datasets[0] && (datasets[0].output_table_name || datasets[0].table_name)) || '';
    var title = (titleInput && titleInput.value) || 'Widget ' + (widgets.length + 1);
    var type = (typeSelect && typeSelect.value) || 'kpi';
    var dim = (dimensionSelect && dimensionSelect.value) || '';
    var measureCol = (measureColSelect && measureColSelect.value) || dim;
    var agg = (measureAggSelect && measureAggSelect.value) || 'sum';
    var limit = (limitInput && parseInt(limitInput.value, 10)) || 100;

    var widgetId = 'w' + Date.now();
    var widget = {
      widget_id: widgetId,
      type: type,
      title: title,
      query: {
        table: table,
        dataset: table,
        dimensions: dim ? [dim] : [],
        measures: [{ column: measureCol, field: measureCol, agg: agg }],
        filters: [],
        limit: limit
      },
      config: {},
      interaction: {}
    };
    widgets.push(widget);

    var grid = document.getElementById('bi-studio-grid');
    if (grid) {
      var y = Math.floor(grid.querySelectorAll('.bi-grid-item').length / 2) * 4;
      layoutItems[widgetId] = { x: 0, y: y, w: 6, h: 4 };
      var div = document.createElement('div');
      div.className = 'bi-grid-item bi-widget bi-card';
      div.setAttribute('data-widget-id', widgetId);
      div.setAttribute('data-type', type);
      div.style.gridColumn = 'span 6';
      div.style.gridRow = 'span 4';
      div.innerHTML = '<div class="bi-widget-title">' + (title || widgetId) + '</div><div class="bi-widget-body"><span class="bi-text-muted">' + type + '</span></div>';
      grid.appendChild(div);
    }
    if (titleInput) titleInput.value = '';
    selectWidget(widgetId);
  }

  function buildLayout() {
    var gridEl = document.getElementById('bi-studio-grid');
    var items = [];
    if (gridEl) {
      var nodes = gridEl.querySelectorAll('.bi-grid-item[data-widget-id]');
      nodes.forEach(function(node, index) {
        var wid = node.getAttribute('data-widget-id');
        var style = node.style;
        var colSpan = (style.gridColumn || '').replace('span ', '') || 6;
        var rowSpan = (style.gridRow || '').replace('span ', '') || 4;
        var w = parseInt(colSpan, 10) || 6;
        var h = parseInt(rowSpan, 10) || 4;
        var x = 0;
        var y = index * 4;
        if (layoutItems[wid]) {
          x = layoutItems[wid].x || 0;
          y = layoutItems[wid].y || y;
          w = layoutItems[wid].w || w;
          h = layoutItems[wid].h || h;
        }
        items.push({ widget_id: wid, x: x, y: y, w: w, h: h });
      });
    }
    return { grid: { columns: 12, rowHeight: 80 }, items: items };
  }

  function save() {
    if (!saveUrl) return;
    applyDataToSelectedWidget();
    applyStyleToSelectedWidget();
    applyInteractionToSelectedWidget();

    var layout = buildLayout();
    var themeEl = document.getElementById('bi-theme-mode');
    var theme = themeEl ? { mode: themeEl.value || 'light' } : {};

    var payload = {
      layout: layout,
      filters: [],
      theme: theme,
      widgets: widgets.map(function(w) {
        return {
          widget_id: w.widget_id || w.id,
          type: w.type || 'kpi',
          title: w.title || '',
          query: w.query || {},
          config: w.config || {},
          interaction_json: w.interaction || {}
        };
      })
    };
    fetch(saveUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data && data.ok) {
          (window.BIToast || function(msg, type) { alert(msg); })('تم الحفظ.', 'success');
        } else {
          alert('فشل الحفظ.');
        }
      })
      .catch(function() {
        alert('خطأ في الاتصال.');
      });
  }

  window.BIStudio = { init: init, addWidget: addWidget, save: save, buildLayout: buildLayout, selectWidget: selectWidget };
})();
