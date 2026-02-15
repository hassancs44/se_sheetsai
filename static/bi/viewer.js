/**
 * SE_SHEETSAI — BI Viewer: lazy load, throttle (4 concurrent), debounced filters, skeleton.
 */
(function() {
  'use strict';

  var dashboardId = null;
  var CHART_TYPES = ['bar', 'line', 'area', 'pie', 'doughnut', 'scatter', 'horizontalbar', 'radar', 'polararea', 'bubble', 'combo'];
  var MAX_CONCURRENT = 4;
  var DEBOUNCE_MS = 400;

  var loadQueue = [];
  var inFlight = 0;
  var loadedIds = {};
  var abortControllers = [];
  var debounceTimer = null;
  var observer = null;

  function getGlobalFilters() {
    var bar = document.getElementById('bi-filter-bar');
    if (!bar) return [];
    var inputs = bar.querySelectorAll('.bi-filter-input');
    var out = [];
    inputs.forEach(function(inp) {
      var key = inp.getAttribute('data-filter-key');
      var val = inp.value != null ? inp.value.trim() : '';
      if (key && val) out.push({ filter_key: key, column: key, value: val });
    });
    return out;
  }

  function skeletonHtml() {
    return '<div class="bi-skeleton"><div class="bi-skeleton-line short"></div><div class="bi-skeleton-line medium"></div><div class="bi-skeleton-line"></div><div class="bi-skeleton-chart"></div></div>';
  }

  function abortAll() {
    abortControllers.forEach(function(ac) { try { ac.abort(); } catch (e) {} });
    abortControllers = [];
  }

  function processQueue() {
    while (inFlight < MAX_CONCURRENT && loadQueue.length > 0) {
      var item = loadQueue.shift();
      if (!item || loadedIds[item.widgetId]) continue;
      inFlight++;
      var ac = new AbortController();
      abortControllers.push(ac);
      loadWidget(item.container, item.dashId, item.widgetId, item.type, function() {
        inFlight--;
        var i = abortControllers.indexOf(ac);
        if (i >= 0) abortControllers.splice(i, 1);
        processQueue();
      }, ac.signal);
    }
  }

  function init(opts) {
    dashboardId = opts.dashboardId || '';
    abortAll();
    loadQueue = [];
    loadedIds = {};
    var nodes = document.querySelectorAll('.widget[data-widget-id][data-dashboard-id], .bi-widget[data-widget-id][data-dashboard-id]');
    if (observer) observer.disconnect();
    observer = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (!entry.isIntersecting) return;
        var el = entry.target;
        var wid = el.getAttribute('data-widget-id');
        if (loadedIds[wid]) return;
        observer.unobserve(el);
        el.classList.add('loading');
        var body = el.querySelector('.widget-body') || el.querySelector('.bi-widget-body');
        if (body) body.innerHTML = skeletonHtml();
        loadQueue.push({
          container: el,
          dashId: el.getAttribute('data-dashboard-id') || dashboardId,
          widgetId: wid,
          type: (el.getAttribute('data-type') || 'table').toLowerCase()
        });
        processQueue();
      });
    }, { rootMargin: '80px', threshold: 0.01 });
    nodes.forEach(function(el) {
      el.classList.add('loading');
      var body = el.querySelector('.widget-body') || el.querySelector('.bi-widget-body');
      if (body) body.innerHTML = skeletonHtml();
      observer.observe(el);
    });
    inFlight = 0;
    bindFilterDebounce();
  }

  function bindFilterDebounce() {
    var applyBtn = document.getElementById('bi-filter-apply');
    if (applyBtn && !applyBtn._biBound) {
      applyBtn._biBound = true;
      applyBtn.onclick = function() {
        if (debounceTimer) clearTimeout(debounceTimer);
        debounceTimer = null;
        init({ dashboardId: dashboardId });
      };
    }
    var bar = document.getElementById('bi-filter-bar');
    if (bar && !bar._biDebounceBound) {
      bar._biDebounceBound = true;
      bar.addEventListener('change', scheduleRefresh);
      bar.addEventListener('input', scheduleRefresh);
    }
  }

  function scheduleRefresh() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(function() {
      debounceTimer = null;
      init({ dashboardId: dashboardId });
    }, DEBOUNCE_MS);
  }

  function loadWidget(container, dashId, widgetId, type, onDone, signal) {
    var body = container.querySelector('.widget-body') || container.querySelector('.bi-widget-body');
    if (!body) {
      if (onDone) onDone();
      return;
    }
    body.innerHTML = skeletonHtml();
    var config = {};
    try {
      var configStr = container.getAttribute('data-config');
      if (configStr) config = JSON.parse(configStr);
    } catch (e) {}

    var filters = getGlobalFilters();
    fetch('/bi/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dashboard_id: dashId, widget_id: widgetId, filters: filters }),
      signal: signal || undefined
    })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        loadedIds[widgetId] = true;
        container.classList.remove('loading');
        if (data.error) {
          body.innerHTML = '<div class="bi-error-state">' + (data.error || 'خطأ') + '</div>';
          if (onDone) onDone();
          return;
        }
        var columns = data.columns || [];
        var rows = data.rows || [];
        if (type === 'kpi' && rows.length > 0 && columns.length > 0) {
          renderKpi(body, columns, rows, config);
        } else if (CHART_TYPES.indexOf(type) >= 0 && rows.length > 0 && columns.length >= 1) {
          var interaction = {};
          try {
            var ia = container.getAttribute('data-interaction');
            if (ia) interaction = JSON.parse(ia);
          } catch (e) {}
          renderChart(body, columns, rows, type, config, container, interaction);
        } else {
          renderTable(body, columns, rows, config);
        }
        if (onDone) onDone();
      })
      .catch(function(err) {
        if (err && err.name === 'AbortError') {
          if (onDone) onDone();
          return;
        }
        loadedIds[widgetId] = true;
        container.classList.remove('loading');
        if (body) body.innerHTML = '<div class="bi-error-state">فشل تحميل البيانات.</div>';
        if (onDone) onDone();
      });
  }

  function renderKpi(body, columns, rows, config) {
    var val = rows[0][columns[0]];
    var disp = val != null ? val : '—';
    var radius = (config.borderRadius != null ? config.borderRadius : 8) + 'px';
    var bg = config.backgroundColor || 'var(--bi-card-bg)';
    body.innerHTML = '<div class="bi-kpi-value" style="border-radius:' + radius + ';background:' + bg + ';padding:1rem;">' + disp + '</div>';
  }

  function renderTable(body, columns, rows, config) {
    var fontFamily = config.fontFamily || 'inherit';
    var html = '<table style="width:100%; border-collapse:collapse; font-size:0.9rem; font-family:' + fontFamily + ';"><thead><tr>';
    columns.forEach(function(c) { html += '<th style="padding:8px 10px; text-align:right; border-bottom:1px solid var(--bi-border); background:var(--bi-background);">' + (c || '') + '</th>'; });
    html += '</tr></thead><tbody>';
    rows.forEach(function(row) {
      html += '<tr>';
      columns.forEach(function(col) { html += '<td style="padding:8px 10px; text-align:right; border-bottom:1px solid var(--bi-border);">' + (row[col] != null ? row[col] : '') + '</td>'; });
      html += '</tr>';
    });
    html += '</tbody></table>';
    body.innerHTML = html;
  }

  function defaultColors() {
    return ['#2563eb', '#16a34a', '#d97706', '#dc2626', '#7c3aed', '#0891b2', '#65a30d', '#be185d'];
  }

  function showDrillModal(label, value) {
    var modal = document.getElementById('bi-drill-modal');
    var body = document.getElementById('bi-drill-modal-body');
    if (!modal || !body) return;
    body.textContent = '';
    var p = document.createElement('p');
    p.textContent = (label != null ? label : '') + ': ' + (value != null ? value : '');
    body.appendChild(p);
    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden', 'false');
    var close = function() {
      modal.style.display = 'none';
      modal.setAttribute('aria-hidden', 'true');
    };
    var back = modal.querySelector('.bi-modal-backdrop');
    var cls = modal.querySelector('.bi-modal-close');
    if (back) back.onclick = close;
    if (cls) cls.onclick = close;
  }

  function renderChart(body, columns, rows, chartType, config, container, interaction) {
    var labelCol = columns[0];
    var valueCol = columns[1] || columns[0];
    var labels = rows.map(function(r) { return r[labelCol] != null ? String(r[labelCol]) : ''; });
    var values = rows.map(function(r) { return Number(r[valueCol]) || 0; });
    var colors = config.colors && config.colors.length ? config.colors : defaultColors();
    var bgColors = colors.slice(0, Math.max(labels.length, values.length));
    while (bgColors.length < labels.length) bgColors.push(bgColors[bgColors.length % colors.length]);
    var borderRadius = config.borderRadius != null ? config.borderRadius : 8;
    var fontFamily = config.fontFamily || 'inherit';
    var showLegend = config.showLegend !== false;
    var showTooltip = config.showTooltip !== false;
    var gridLines = config.gridLines !== false;
    var useGradient = config.gradient === true;

    var canvas = document.createElement('canvas');
    body.innerHTML = '';
    body.appendChild(canvas);

    var type = chartType === 'area' ? 'line' : (chartType === 'horizontalbar' ? 'bar' : (chartType === 'doughnut' ? 'doughnut' : (chartType === 'polararea' ? 'polarArea' : chartType)));
    if (chartType === 'combo') type = 'bar';

    var dataset = {
      label: valueCol,
      data: chartType === 'bubble' ? rows.map(function(r) {
        return { x: Number(r[columns[0]]) || 0, y: Number(r[columns[1]]) || 0, r: Math.max(5, (Number(r[columns[2]]) || 10) / 5 };
      }) : values,
      backgroundColor: chartType === 'pie' || chartType === 'doughnut' ? bgColors : (chartType === 'bar' || chartType === 'horizontalbar' ? bgColors : (bgColors[0] || 'rgba(37,99,235,0.5)')),
      borderColor: colors[0] || '#2563eb',
      borderWidth: 1,
      fill: chartType === 'area',
      tension: 0.3,
      borderRadius: (chartType === 'bar' || chartType === 'horizontalbar') ? borderRadius : 0
    };

    if (chartType === 'radar' || chartType === 'polararea') {
      dataset.backgroundColor = bgColors.map(function(c) { return c.indexOf('rgba') === 0 ? c : (c + '99'); });
      dataset.borderColor = colors;
      dataset.borderWidth = 2;
    }

    if (chartType === 'scatter') {
      dataset.data = rows.map(function(r) { return { x: Number(r[columns[0]]) || 0, y: Number(r[columns[1]]) || 0 }; });
    }

    var chartConfig = {
      type: type,
      data: { labels: labels, datasets: [dataset] },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        animation: config.animation !== false,
        plugins: {
          legend: { display: showLegend, labels: { font: { family: fontFamily } } },
          tooltip: { enabled: showTooltip }
        },
        scales: (chartType !== 'pie' && chartType !== 'doughnut' && chartType !== 'radar' && chartType !== 'polararea') ? {
          x: { grid: { display: gridLines }, ticks: { font: { family: fontFamily } } },
          y: { grid: { display: gridLines }, beginAtZero: true, ticks: { font: { family: fontFamily } } }
        } : {}
      }
    };

    if (chartType === 'horizontalbar') {
      chartConfig.options.indexAxis = 'y';
      chartConfig.options.scales = {
        x: { grid: { display: gridLines }, beginAtZero: true, ticks: { font: { family: fontFamily } } },
        y: { grid: { display: gridLines }, ticks: { font: { family: fontFamily } } }
      };
    }

    if (chartType === 'radar') {
      chartConfig.options.scales = { r: { grid: { display: gridLines }, ticks: { font: { family: fontFamily } } } };
    }

    if (chartType === 'pie' || chartType === 'doughnut') {
      chartConfig.data.datasets[0].backgroundColor = bgColors;
      chartConfig.data.datasets[0].borderColor = '#fff';
      chartConfig.data.datasets[0].borderWidth = 2;
      chartConfig.options.plugins.datalabels = false;
    }

    if (chartType === 'combo' && columns.length >= 2) {
      chartConfig.data.datasets.push({
        label: valueCol + ' (خط)',
        data: values,
        type: 'line',
        borderColor: colors[1] || '#16a34a',
        backgroundColor: 'transparent',
        fill: false,
        tension: 0.3
      });
    }

    if (useGradient && (chartType === 'bar' || chartType === 'horizontalbar') && dataset.backgroundColor) {
      var baseColor = colors[0] || '#2563eb';
      chartConfig.data.datasets[0].backgroundColor = function(context) {
        var ch = context.chart;
        var ctx = ch.ctx;
        var area = ch.chartArea;
        if (!ctx || !area) return baseColor;
        var g = ctx.createLinearGradient(0, area.bottom, 0, area.top);
        g.addColorStop(0, baseColor.replace('#', '') + '40');
        g.addColorStop(1, baseColor);
        return g;
      };
    }

    var drillEnabled = interaction && interaction.drill && interaction.drill.enabled;
    if (drillEnabled) {
      chartConfig.options.onClick = function(ev, elements, ch) {
        if (elements.length && ch && ch.data) {
          var i = elements[0].index;
          var label = (ch.data.labels && ch.data.labels[i]) != null ? ch.data.labels[i] : '';
          var val = (ch.data.datasets && ch.data.datasets[0] && ch.data.datasets[0].data && ch.data.datasets[0].data[i]) != null ? ch.data.datasets[0].data[i] : '';
          showDrillModal(label, val);
        }
      };
    }

    new Chart(canvas, chartConfig);
  }

  window.BIViewer = { init: init, getGlobalFilters: getGlobalFilters };
})();
