'use strict';

/* One dependency-free script for the browser, its counting worker and Node tests. */
(() => {
  const MAX_PIXELS = 4000000;

  function validateDimensions(width, height) {
    if (!Number.isSafeInteger(width) || !Number.isSafeInteger(height) || width < 1 || height < 1) {
      throw new Error('The image has invalid dimensions.');
    }
    if (width > MAX_PIXELS / height) {
      throw new Error('This image exceeds the 4 million pixel histogram limit. Use a smaller image; downloads are unaffected.');
    }
    return width * height;
  }

  function countRGB(rgba, width, height) {
    const pixels = validateDimensions(width, height);
    if (!(rgba instanceof Uint8Array || rgba instanceof Uint8ClampedArray) || rgba.length !== pixels * 4) {
      throw new Error('Expected one decoded RGBA byte sample per pixel.');
    }
    const channels = [new Uint32Array(256), new Uint32Array(256), new Uint32Array(256)];
    for (let offset = 0; offset < rgba.length; offset += 4) {
      channels[0][rgba[offset]]++;
      channels[1][rgba[offset + 1]]++;
      channels[2][rgba[offset + 2]]++;
    }
    return { width, height, pixels, channels };
  }

  function seriesFor(original, encoded, view, channel = 'all') {
    const channels = channel === 'all' ? [0, 1, 2] : [Number(channel)].filter((value) => [0, 1, 2].includes(value));
    if (view === 'difference') return original && encoded ? channels.map((index) => ({
      kind: 'difference', channel: index,
      counts: Int32Array.from(encoded.channels[index], (value, bin) => value - original.channels[index][bin]),
    })) : [];
    const images = view === 'overlay' ? [['source', original], ['result', encoded]] : [[view, view === 'result' ? encoded : original]];
    return images.filter(([, data]) => data).flatMap(([kind, data]) => channels.map((index) => ({ kind, channel: index, counts: data.channels[index] })));
  }

  const scaleValue = (value, scale) => scale === 'log' ? Math.sign(value) * Math.log1p(Math.abs(value)) : value;
  const binAt = (x, left, right) => Math.max(0, Math.min(255, Math.round((x - left) / (right - left) * 255)));

  function valuesAt(original, encoded, bin) {
    return [0, 1, 2].map((channel) => {
      const before = original ? original.channels[channel][bin] : null;
      const after = encoded ? encoded.channels[channel][bin] : null;
      return { channel, original: before, encoded: after, delta: before !== null && after !== null ? after - before : null,
        originalPercent: original ? before / original.pixels * 100 : null,
        encodedPercent: encoded ? after / encoded.pixels * 100 : null };
    });
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { MAX_PIXELS, validateDimensions, countRGB, seriesFor, scaleValue, binAt, valuesAt };
    return;
  }
  if (typeof document === 'undefined') {
    self.onmessage = ({ data }) => {
      try {
        const result = countRGB(new Uint8ClampedArray(data.rgba), data.width, data.height);
        self.postMessage(result, result.channels.map((channel) => channel.buffer));
      } catch (error) {
        self.postMessage({ error: error.message });
      }
    };
    return;
  }

  const workerURL = document.currentScript ? document.currentScript.src : '/histogram.js';
  let source = null;
  let result = null;
  let selected = 'source';
  let expanded = false;
  let generation = 0;
  let worker = null;
  let rejectWorker = null;
  let ui = null;
  let channel = 'all';
  let scale = 'log';
  let current = { source: null, result: null };
  let chart = null;
  let probe = null;
  const cache = new WeakMap();
  const colours = ['#ff9696', '#9bdda5', '#9fc6ff'];
  const format = (value) => value.toLocaleString('en-US');
  const abortError = () => new DOMException('Histogram cancelled.', 'AbortError');

  function cancel() {
    generation++;
    if (worker) worker.terminate();
    if (rejectWorker) rejectWorker(abortError());
    worker = null;
    rejectWorker = null;
  }

  function clearPlot() {
    if (!ui) return;
    chart = null;
    current = { source: null, result: null };
    hideProbe();
    ui.plot.hidden = true;
    ui.summary.textContent = '';
    ui.canvas.width = 1;
    ui.canvas.height = 1;
    ui.panel.setAttribute('aria-busy', 'false');
    ui.status.textContent = '';
  }

  function element(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text) item.textContent = text;
    return item;
  }

  function mount() {
    if (ui) return true;
    const host = document.getElementById('histogramMount');
    if (!host) return false;
    const section = element('section', 'image-histogram');
    section.setAttribute('aria-label', 'Image histogram');

    const panel = element('div', 'histogram-panel');
    panel.id = 'imageHistogramPanel';
    panel.hidden = true;
    panel.append(element('h2', '', 'Decoded RGB histogram'));
    const help = element('p', 'histogram-help', 'Browser-decoded RGB values, not JPEG DCT coefficients or hidden payload bits. Alpha is ignored; browser colour conversion and transparency normalisation can affect values. JPEG decoding includes compression effects. Full resolution, up to 4 million pixels; no downsampling.');
    const label = element('label', 'histogram-selector', 'View');
    const select = element('select');
    select.setAttribute('aria-label', 'Histogram image');
    label.append(select);
    const controls = element('div', 'histogram-controls');
    const channelLabel = element('label', 'histogram-selector', 'Channel');
    const channelSelect = element('select');
    channelSelect.setAttribute('aria-label', 'Histogram channel');
    for (const [value, text] of [['all', 'RGB'], ['0', 'Red'], ['1', 'Green'], ['2', 'Blue']]) {
      const option = element('option', '', text); option.value = value; channelSelect.append(option);
    }
    channelSelect.value = channel;
    channelLabel.append(channelSelect);
    const scaleLabel = element('label', 'histogram-selector', 'Scale');
    const scaleSelect = element('select');
    scaleSelect.setAttribute('aria-label', 'Histogram scale');
    for (const [value, text] of [['log', 'Logarithmic'], ['linear', 'Linear']]) {
      const option = element('option', '', text); option.value = value; scaleSelect.append(option);
    }
    scaleSelect.value = scale;
    scaleLabel.append(scaleSelect);
    controls.append(label, channelLabel, scaleLabel);
    const status = element('p', 'histogram-status');
    status.setAttribute('role', 'status');
    status.setAttribute('aria-live', 'polite');
    const plot = element('div', 'histogram-plot');
    plot.hidden = true;
    const canvas = element('canvas');
    canvas.id = 'histogramCanvas';
    canvas.tabIndex = 0;
    canvas.setAttribute('role', 'slider');
    canvas.setAttribute('aria-label', 'Histogram intensity. Use left and right arrows to inspect bins, Home and End for endpoints.');
    canvas.setAttribute('aria-valuemin', '0');
    canvas.setAttribute('aria-valuemax', '255');
    canvas.setAttribute('aria-valuenow', '128');
    canvas.setAttribute('aria-describedby', 'imageHistogramSummary');
    canvas.append(document.createTextNode('The decoded RGB histogram is described in the text below.'));
    const axes = element('p', 'histogram-axes');
    const legend = element('div', 'histogram-legend');
    const stage = element('div', 'histogram-stage');
    const crosshair = element('div', 'histogram-crosshair');
    crosshair.setAttribute('aria-hidden', 'true'); crosshair.hidden = true;
    const vertical = element('span', 'histogram-crosshair-vertical');
    const horizontal = element('span', 'histogram-crosshair-horizontal');
    const markers = element('div', 'histogram-markers');
    crosshair.append(vertical, horizontal, markers);
    const tooltip = element('div', 'histogram-tooltip');
    tooltip.id = 'histogramTooltip'; tooltip.hidden = true;
    tooltip.setAttribute('role', 'status'); tooltip.setAttribute('aria-live', 'off');
    stage.append(canvas, crosshair, tooltip);
    const summary = element('div', 'histogram-summary');
    summary.id = 'imageHistogramSummary';
    plot.append(legend, stage, axes, summary);
    panel.append(help, controls, status, plot);
    section.append(panel);
    host.append(section);
    ui = { section, panel, select, status, plot, canvas, summary, axes, legend, stage, crosshair, vertical, horizontal, markers, tooltip, channelSelect, scaleSelect };
    select.addEventListener('change', () => {
      selected = select.value;
      cancel();
      clearPlot();
      if (expanded) void render();
    });
    for (const [control, updateValue] of [[channelSelect, () => { channel = channelSelect.value; }], [scaleSelect, () => { scale = scaleSelect.value; }]]) {
      control.addEventListener('change', () => { updateValue(); hideProbe(); if (chart) draw(); });
    }
    canvas.addEventListener('pointermove', (event) => {
      if (!chart || event.pointerType === 'touch') return;
      pointAt(event);
    });
    canvas.addEventListener('pointerdown', (event) => { if (chart) pointAt(event); });
    canvas.addEventListener('pointerleave', (event) => { if (event.pointerType !== 'touch') hideProbe(); });
    canvas.addEventListener('blur', hideProbe);
    canvas.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') { hideProbe(); return; }
      if (!chart || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const bin = event.key === 'Home' ? 0 : event.key === 'End' ? 255 : Math.max(0, Math.min(255, (probe ?? 128) + (event.key === 'ArrowLeft' ? -1 : 1)));
      showProbe(bin, null, true);
    });
    if (typeof ResizeObserver === 'function') new ResizeObserver(() => {
      if (chart && expanded && chart.displayWidth !== canvas.clientWidth) { hideProbe(); draw(); }
    }).observe(canvas);
    return true;
  }

  function sync() {
    if (!mount()) return;
    ui.section.hidden = !expanded || (!source && !result);
    ui.panel.hidden = !expanded;
    ui.select.replaceChildren();
    for (const [value, blob, name] of [['source', source, 'Original image'], ['result', result, 'Encoded image'], ['overlay', source && result, 'Original + encoded'], ['difference', source && result, 'Difference (encoded − original)']]) {
      if (!blob) continue;
      const option = element('option', '', name);
      option.value = value;
      ui.select.append(option);
    }
    ui.select.value = selected;
    ui.select.disabled = !(source && result);
  }

  async function analyse(blob, token) {
    if (typeof createImageBitmap !== 'function' || typeof Worker !== 'function') {
      throw new Error('Histogram analysis is unavailable in this browser. Try a current browser; downloads are unaffected.');
    }
    let bitmap;
    let canvas;
    try {
      bitmap = await createImageBitmap(blob);
      if (token !== generation) throw abortError();
      const { width, height } = bitmap;
      validateDimensions(width, height);
      canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext('2d', { willReadFrequently: true });
      if (!ctx) throw new Error('Canvas analysis is unavailable.');
      ctx.drawImage(bitmap, 0, 0);
      const rgba = ctx.getImageData(0, 0, width, height).data;
      if (token !== generation) throw abortError();
      return await new Promise((resolve, reject) => {
        rejectWorker = reject;
        worker = new Worker(workerURL);
        worker.onmessage = ({ data }) => data.error ? reject(new Error(data.error)) : resolve(data);
        worker.onerror = () => reject(new Error('Background histogram analysis failed. Close and reopen to retry.'));
        worker.onmessageerror = () => reject(new Error('The histogram result could not be read.'));
        worker.postMessage({ rgba: rgba.buffer, width, height }, [rgba.buffer]);
      });
    } finally {
      if (bitmap) bitmap.close();
      if (canvas) { canvas.width = 1; canvas.height = 1; }
      if (token === generation) {
        if (worker) worker.terminate();
        worker = null;
        rejectWorker = null;
      }
    }
  }

  function draw() {
    const { canvas, summary } = ui;
    const series = seriesFor(current.source, current.result, selected, channel);
    if (!series.length) return;
    ui.plot.hidden = false;
    const displayWidth = canvas.clientWidth || 1024;
    const unit = 1024 / displayWidth;
    const fontSize = Math.max(14, 12 * unit);
    canvas.width = 1024;
    canvas.height = Math.round((displayWidth < 540 ? 320 : 380) * unit);
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('The histogram chart could not be drawn.');
    let peak = 1;
    for (const { counts } of series) for (const count of counts) peak = Math.max(peak, Math.abs(count));
    const delta = selected === 'difference';
    const limit = scaleValue(peak, scale);
    const left = Math.max(72 * unit, fontSize * 6), right = 1024 - 18 * unit, top = 22 * unit, bottom = canvas.height - 34 * unit;
    const y = (value) => bottom - ((scaleValue(value, scale) + (delta ? limit : 0)) / (delta ? 2 * limit : limit)) * (bottom - top);
    chart = { left, right, top, bottom, series, y, peak, displayWidth };
    for (const [key, value] of Object.entries({ left, right, top, bottom })) canvas.setAttribute(`data-plot-${key}`, String(value));
    canvas.setAttribute('data-scale', scale);
    ctx.font = `${fontSize}px sans-serif`;
    ctx.fillStyle = '#c2c2c2';
    const positiveTicks = scale === 'log' ? [0, 1] : [0, peak / 4, peak / 2, peak * 3 / 4];
    if (scale === 'log') for (let value = 10; value < peak; value *= 10) positiveTicks.push(value);
    // Avoid a label almost on top of the maximum when it is near a decade.
    const ticks = [...new Set([...positiveTicks.filter((value) => value === 0 || scaleValue(value, scale) < limit * .92), peak])];
    if (delta) ticks.unshift(...ticks.filter((value) => value > 0).map((value) => -value));
    for (const value of ticks) {
      ctx.strokeStyle = value === 0 ? '#8b8b8b' : '#343434';
      ctx.lineWidth = (value === 0 ? 1.3 : .8) * unit;
      const py = y(value);
      ctx.beginPath(); ctx.moveTo(left, py); ctx.lineTo(right, py); ctx.stroke();
      ctx.textAlign = 'right';
      const label = Math.abs(value) < 1 && value !== 0 ? value.toFixed(2) : format(Math.round(value));
      ctx.fillText(label, left - 10 * unit, py + fontSize / 3);
    }
    for (const value of [0, 64, 128, 192, 255]) {
      const x = left + (right - left) * value / 255;
      ctx.strokeStyle = '#282828'; ctx.lineWidth = .8 * unit;
      ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
      ctx.textAlign = value === 0 ? 'left' : value === 255 ? 'right' : 'center';
      ctx.fillText(String(value), x, canvas.height - 10 * unit);
    }
    ui.legend.replaceChildren();
    for (const index of channel === 'all' ? [0, 1, 2] : [Number(channel)]) {
      const item = element('span', `histogram-channel histogram-channel-${index}`, ['Red', 'Green', 'Blue'][index]);
      ui.legend.append(item);
    }
    ui.legend.append(element('span', 'histogram-line-key', delta ? 'Encoded − original · zero = no change' : selected === 'overlay' ? 'Original: solid · Encoded: dashed' : selected === 'result' ? 'Encoded image' : 'Original image'));
    for (const item of series) {
      ctx.strokeStyle = colours[item.channel];
      ctx.globalAlpha = selected === 'overlay' && item.kind === 'source' ? .65 : 1;
      ctx.lineWidth = (item.kind === 'result' && selected === 'overlay' ? 2.5 : 1.8) * unit;
      ctx.setLineDash(item.kind === 'result' && selected === 'overlay' ? [7 * unit, 4 * unit] : []);
      ctx.beginPath();
      for (let bin = 0; bin < 256; bin++) {
        const x = left + (right - left) * bin / 255;
        if (bin === 0) ctx.moveTo(x, y(item.counts[bin])); else ctx.lineTo(x, y(item.counts[bin]));
      }
      ctx.stroke();
    }
    ctx.globalAlpha = 1; ctx.setLineDash([]);
    ui.axes.textContent = `Intensity: 0–255 · ${delta ? 'Count difference' : 'Pixel count'} · ${scale === 'log' ? (delta ? 'Signed logarithmic scale (log₁₊)' : 'Logarithmic scale (log₁₊)') : 'Linear scale'}. Hover, tap or use ← / → for exact values.`;
    const data = selected === 'result' ? current.result : current.source || current.result;
    summary.replaceChildren(element('p', '', `${selected === 'overlay' ? 'Original + encoded' : delta ? 'Difference' : selected === 'source' ? 'Original' : 'Encoded'} image: ${format(data.width)} × ${format(data.height)}; ${format(data.pixels)} pixels counted in every channel. 256 bins per channel.`));
    if (delta || selected === 'overlay') summary.append(element('p', '', 'Counts share the same scale. Δ is encoded minus original per intensity bin, not a count of modified pixels. Use Difference to isolate small changes.'));
    else data.channels.forEach((counts, index) => {
      if (channel !== 'all' && Number(channel) !== index) return;
      let sum = 0, min = 255, max = 0, mode = 0;
      for (let bin = 0; bin < 256; bin++) {
        if (counts[bin]) { min = Math.min(min, bin); max = bin; }
        if (counts[bin] > counts[mode]) mode = bin;
        sum += bin * counts[bin];
      }
      summary.append(element('p', '', `${['Red (R)', 'Green (G)', 'Blue (B)'][index]}: range ${min}–${max}; mean ${(sum / data.pixels).toFixed(2)}; most frequent intensity ${mode} (${format(counts[mode])} pixels; lowest intensity shown for ties).`));
    });
  }

  function hideProbe() {
    probe = null;
    if (!ui) return;
    ui.crosshair.hidden = true;
    ui.tooltip.hidden = true;
    ui.tooltip.replaceChildren();
    ui.markers.replaceChildren();
  }

  function pointAt(event) {
    const rect = ui.canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width * ui.canvas.width;
    const y = (event.clientY - rect.top) / rect.height * ui.canvas.height;
    if (x < chart.left || x > chart.right || y < chart.top || y > chart.bottom) { hideProbe(); return; }
    showProbe(binAt(x, chart.left, chart.right), y, false);
  }

  function showProbe(bin, pointerY, keyboard) {
    if (!chart) return;
    probe = bin;
    const { left, right, top, bottom, series, y } = chart;
    const x = left + (right - left) * bin / 255;
    const py = pointerY ?? y(series[0].counts[bin]);
    ui.canvas.setAttribute('aria-valuenow', String(bin));
    ui.tooltip.setAttribute('data-intensity', String(bin));
    ui.tooltip.setAttribute('aria-live', keyboard ? 'polite' : 'off');
    ui.crosshair.hidden = false;
    ui.crosshair.style.height = `${ui.canvas.clientHeight || ui.canvas.height}px`;
    ui.vertical.style.left = `${x / ui.canvas.width * 100}%`;
    ui.vertical.style.top = `${top / ui.canvas.height * 100}%`;
    ui.vertical.style.height = `${(bottom - top) / ui.canvas.height * 100}%`;
    ui.horizontal.style.left = `${left / ui.canvas.width * 100}%`;
    ui.horizontal.style.width = `${(right - left) / ui.canvas.width * 100}%`;
    ui.horizontal.style.top = `${py / ui.canvas.height * 100}%`;
    ui.markers.replaceChildren();
    for (const item of series) {
      const marker = element('span', `histogram-marker histogram-marker-${item.kind}`);
      marker.style.left = `${x / ui.canvas.width * 100}%`;
      marker.style.top = `${y(item.counts[bin]) / ui.canvas.height * 100}%`;
      marker.style.borderColor = colours[item.channel];
      ui.markers.append(marker);
    }
    ui.tooltip.replaceChildren(element('strong', 'histogram-tooltip-title', `Intensity ${bin}`));
    const table = element('table');
    const header = element('tr');
    for (const label of ['Channel', ...(current.source ? ['Original'] : []), ...(current.result ? ['Encoded'] : []), ...(current.source && current.result ? ['Δ'] : [])]) header.append(element('th', '', label));
    const head = element('thead'); head.append(header); table.append(head);
    const body = element('tbody');
    for (const row of valuesAt(current.source, current.result, bin)) {
      if (channel !== 'all' && row.channel !== Number(channel)) continue;
      const tr = element('tr'); tr.setAttribute('data-channel', String(row.channel));
      tr.append(element('th', `histogram-channel-${row.channel}`, ['R', 'G', 'B'][row.channel]));
      for (const kind of ['original', 'encoded']) {
        if (row[kind] === null) continue;
        const cell = element('td'); cell.setAttribute('data-kind', kind);
        cell.append(element('b', '', format(row[kind])), element('small', '', `${row[`${kind}Percent`].toLocaleString('en-US', { maximumFractionDigits: 6 })}%`));
        tr.append(cell);
      }
      if (row.delta !== null) {
        const cell = element('td', '', `${row.delta > 0 ? '+' : ''}${format(row.delta)}`);
        cell.setAttribute('data-kind', 'delta'); tr.append(cell);
      }
      body.append(tr);
    }
    table.append(body); ui.tooltip.append(table);
    ui.tooltip.hidden = false;
    const width = ui.stage.clientWidth || 1024;
    const tooltipWidth = ui.tooltip.offsetWidth || 300;
    const cursorX = x / ui.canvas.width * width;
    const available = Math.max(0, width - tooltipWidth - 8);
    ui.tooltip.style.left = `${Math.max(8, Math.min(available, cursorX + 18 > available ? cursorX - tooltipWidth - 18 : cursorX + 18))}px`;
    ui.tooltip.style.top = '12px';
    const spoken = valuesAt(current.source, current.result, bin).filter((row) => channel === 'all' || row.channel === Number(channel)).map((row) => `${['Red', 'Green', 'Blue'][row.channel]}: ${row.original === null ? '' : `original ${row.original}, `}${row.encoded === null ? '' : `encoded ${row.encoded}, `}${row.delta === null ? '' : `difference ${row.delta}`}`).join('; ');
    ui.canvas.setAttribute('aria-valuetext', `Intensity ${bin}. ${spoken}`);
  }

  async function render() {
    const needed = selected === 'overlay' || selected === 'difference' ? ['source', 'result'] : [selected];
    if (!expanded || !ui || needed.some((kind) => !(kind === 'result' ? result : source))) return;
    const token = generation;
    ui.status.textContent = 'Computing histogram…';
    ui.panel.setAttribute('aria-busy', 'true');
    try {
      const data = { source: null, result: null };
      for (const kind of needed) {
        const blob = kind === 'result' ? result : source;
        data[kind] = cache.get(blob) || await analyse(blob, token);
        if (token !== generation || !expanded) return;
        cache.set(blob, data[kind]);
      }
      if (token !== generation || !expanded) return;
      current = data;
      draw();
      ui.status.textContent = '';
    } catch (error) {
      if (token !== generation || !expanded) return;
      clearPlot();
      ui.status.textContent = `Histogram unavailable. ${error.message || 'The image could not be decoded.'} Encoding, extraction and downloads are unaffected.`;
    } finally {
      if (token === generation) ui.panel.setAttribute('aria-busy', 'false');
    }
  }

  function update() {
    cancel();
    clearPlot();
    sync();
    if (expanded) void render();
  }

  window.ImageHistogram = Object.freeze({
    open() {
      if (expanded || (!source && !result)) return;
      expanded = true;
      update();
    },
    close() {
      expanded = false;
      update();
    },
    setSource(file) {
      source = file || null;
      result = null;
      selected = 'source';
      expanded = false;
      update();
    },
    setResult(blob) {
      result = blob || null;
      selected = result && source ? 'overlay' : result ? 'result' : 'source';
      update();
    },
    resetResult() {
      result = null;
      selected = 'source';
      update();
    },
    reset() {
      source = null;
      result = null;
      selected = 'source';
      expanded = false;
      update();
    },
  });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', sync, { once: true });
  else sync();
})();
