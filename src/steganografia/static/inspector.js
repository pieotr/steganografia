'use strict';

(() => {
  const $ = (id) => document.getElementById(id);
  let context = null;
  let analysis = null;
  let worker = null;
  let cancelWorker = null;
  let generation = 0;
  let pending = false;
  let mapFrame = null;
  let selectedPixel = { x: 0, y: 0 };
  const number = (value) => value.toLocaleString('en-US');
  const size = (bytes) => `${number(bytes)} B`;

  function reset() {
    generation += 1;
    if (worker) worker.terminate();
    if (cancelWorker) cancelWorker(new DOMException('Inspection cancelled.', 'AbortError'));
    worker = null;
    cancelWorker = null;
    if (mapFrame !== null) cancelAnimationFrame(mapFrame);
    mapFrame = null;
    pending = false;
    context = null;
    analysis = null;
    $('inspectButton').hidden = true;
    $('inspectButton').textContent = 'Inspect changes';
    $('inspectButton').setAttribute('aria-expanded', 'false');
    $('changeInspector').hidden = true;
    $('inspectorContent').hidden = true;
    $('inspectorStatus').textContent = '';
    $('inspectorStatus').hidden = true;
    $('pixelBitRows').replaceChildren();
    $('inspectBefore').removeAttribute('src');
    $('inspectAfter').removeAttribute('src');
    $('changeMap').width = 1;
    $('changeMap').height = 1;
    selectedPixel = { x: 0, y: 0 };
    $('pixelX').value = 0;
    $('pixelY').value = 0;
    clearCoordinateErrors();
  }

  function prepare(next) {
    reset();
    context = next;
    $('inspectButton').hidden = false;
  }

  function setView(heatmap) {
    $('compareView').hidden = heatmap;
    $('heatmapView').hidden = !heatmap;
    $('compareViewButton').setAttribute('aria-pressed', String(!heatmap));
    $('heatmapViewButton').setAttribute('aria-pressed', String(heatmap));
    if (heatmap) drawMap();
  }

  function comparePosition() {
    const position = Number($('comparePosition').value);
    $('compareStage').style.setProperty('--comparison', `${position}%`);
    $('compareValue').value = `${position}% before`;
  }

  function clearCoordinateErrors() {
    $('pixelX').removeAttribute('aria-invalid');
    $('pixelY').removeAttribute('aria-invalid');
    $('coordinateError').hidden = true;
    $('coordinateError').textContent = '';
  }

  function pixelDetails(x, y, syncInputs = true) {
    if (!analysis) return;
    const { summary, before, after } = analysis;
    x = Math.max(0, Math.min(summary.width - 1, Math.trunc(Number(x)) || 0));
    y = Math.max(0, Math.min(summary.height - 1, Math.trunc(Number(y)) || 0));
    selectedPixel = { x, y };
    if (syncInputs) {
      $('pixelX').value = x;
      $('pixelY').value = y;
    }
    clearCoordinateErrors();

    const offset = (y * summary.width + x) * 4;

    $('pixelBitRows').replaceChildren();
    ['R', 'G', 'B'].forEach((channel, index) => {
      const oldValue = before[offset + index];
      const newValue = after[offset + index];
      const row = document.createElement('tr');
      const heading = document.createElement('th');
      heading.scope = 'row';
      heading.textContent = channel;
      row.append(heading);
      for (const value of [oldValue, newValue]) {
        const cell = document.createElement('td');
        cell.textContent = value;
        row.append(cell);
      }
      const bits = document.createElement('td');
      const oldBits = oldValue.toString(2).padStart(8, '0');
      const newBits = newValue.toString(2).padStart(8, '0');
      const oldCode = document.createElement('code');
      const newCode = document.createElement('code');
      for (let bit = 0; bit < 8; bit += 1) {
        for (const [code, value] of [[oldCode, oldBits[bit]], [newCode, newBits[bit]]]) {
          const element = document.createElement(oldBits[bit] !== newBits[bit] ? 'mark' : 'span');
          element.textContent = value;
          code.append(element);
        }
      }
      bits.append(oldCode, document.createTextNode(' → '), newCode);
      row.append(bits);
      $('pixelBitRows').append(row);
    });
  }

  function drawMap() {
    if (!analysis) return;
    const { previewWidth: width, previewHeight: height, previewBefore, previewDelta } = analysis;
    const canvas = $('changeMap');
    canvas.width = width;
    canvas.height = height;
    canvas.style.width = `${Math.round(Math.min(640, width / height * 480))}px`;
    const ctx = canvas.getContext('2d');
    const image = ctx.createImageData(width, height);
    const gain = Number($('differenceGain').value);
    $('gainValue').value = `${gain}×`;
    for (let pixel = 0; pixel < width * height; pixel += 1) {
      const offset = pixel * 4;
      const dimmed = (previewBefore[offset] + previewBefore[offset + 1] + previewBefore[offset + 2]) / 3 * 0.24;
      const intensity = Math.min(255, previewDelta[pixel] * gain);
      image.data[offset] = dimmed;
      image.data[offset + 1] = Math.max(dimmed, intensity * 0.8);
      image.data[offset + 2] = Math.max(dimmed, intensity);
      image.data[offset + 3] = 255;
    }
    ctx.putImageData(image, 0, 0);
  }

  async function loadPixels(item, token) {
    const results = await Promise.allSettled([
      createImageBitmap(item.file, { imageOrientation: 'none', colorSpaceConversion: 'none' }),
      createImageBitmap(item.encodedBlob, { imageOrientation: 'none', colorSpaceConversion: 'none' }),
    ]);
    const bitmaps = results.filter((result) => result.status === 'fulfilled').map((result) => result.value);
    try {
      if (token !== generation) throw new DOMException('Inspection cancelled.', 'AbortError');
      if (results.some((result) => result.status === 'rejected')) throw new Error('This image could not be decoded for inspection. You can still download the encoded file.');
      const [before, after] = bitmaps;
      if (before.width !== after.width || before.height !== after.height) throw new Error('Image dimensions differ. Pixel-by-pixel analysis is unavailable.');
      if (before.width * before.height > 4000000) throw new Error('This image exceeds the 4 million pixel inspection limit. The encoded download is unaffected. Try a smaller image to inspect changes.');
      const arrays = bitmaps.map((bitmap) => {
        const canvas = document.createElement('canvas');
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        ctx.drawImage(bitmap, 0, 0);
        const pixels = ctx.getImageData(0, 0, bitmap.width, bitmap.height).data;
        canvas.width = 1;
        canvas.height = 1;
        return pixels;
      });
      worker = new Worker('/inspection-worker.js?v=inspect1');
      return await new Promise((resolve, reject) => {
        cancelWorker = reject;
        worker.onmessage = ({ data }) => {
          if (data.error) reject(new Error(data.error));
          else resolve({ ...data, before: new Uint8ClampedArray(data.before), after: new Uint8ClampedArray(data.after) });
        };
        worker.onerror = () => reject(new Error('Background inspection failed. Retry, or use another browser. Your encoded download is unaffected.'));
        worker.postMessage({ before: arrays[0].buffer, after: arrays[1].buffer, width: before.width, height: before.height }, [arrays[0].buffer, arrays[1].buffer]);
      });
    } finally {
      bitmaps.forEach((bitmap) => bitmap.close());
      if (token === generation) {
        if (worker) worker.terminate();
        worker = null;
        cancelWorker = null;
      }
    }
  }

  async function open() {
    if (!context) return;
    if (!$('changeInspector').hidden) {
      close();
      return;
    }
    $('changeInspector').hidden = false;
    $('inspectButton').textContent = 'Hide changes';
    $('inspectButton').setAttribute('aria-expanded', 'true');
    $('changeInspector').scrollIntoView({ block: 'start', behavior: 'auto' });
    if (analysis || pending) return;
    const token = generation;
    const item = context;
    pending = true;
    $('inspectorStatus').textContent = 'Comparing full-resolution RGB pixels in your browser…';
    $('inspectorStatus').hidden = false;
    try {
      analysis = await loadPixels(item, token);
      if (token !== generation) return;
      const summary = analysis.summary;
      $('inspectMessageBytes').textContent = `${number(item.messageBytes)} B`;
      $('inspectChangedPixels').textContent = `${number(summary.changedPixels)} / ${number(summary.totalPixels)} (${(summary.changedPixels / summary.totalPixels * 100).toFixed(3)}%)`;
      $('inspectFlippedBits').textContent = number(summary.flippedBits);
      $('inspectFileSizes').textContent = `${size(item.file.size)} → ${size(item.encodedBlob.size)}`;

      $('comparisonFrame').style.setProperty('--compare-width', `${Math.min(640, summary.width / summary.height * 520)}px`);
      $('pixelX').max = summary.width - 1;
      $('pixelY').max = summary.height - 1;
      $('pixelLimits').textContent = `X: 0–${summary.width - 1} · Y: 0–${summary.height - 1}`;
      $('inspectBefore').src = item.sourceUrl;
      $('inspectAfter').src = item.resultUrl;
      await Promise.all([$('inspectBefore').decode(), $('inspectAfter').decode()]);
      if (token !== generation) return;
      $('comparePosition').value = 50;
      $('differenceGain').value = 64;
      comparePosition();
      pixelDetails(summary.firstChanged?.x || 0, summary.firstChanged?.y || 0);
      setView(false);
      $('inspectorContent').hidden = false;
      $('inspectorStatus').textContent = '';
      $('inspectorStatus').hidden = true;
    } catch (error) {
      if (token === generation) {
        analysis = null;
        $('inspectorStatus').textContent = error.message || 'Inspection failed. Your download is still available.';
        $('inspectorStatus').hidden = false;
      }
    } finally {
      if (token === generation) pending = false;
    }
  }

  function close() {
    $('changeInspector').hidden = true;
    $('inspectButton').textContent = 'Inspect changes';
    $('inspectButton').setAttribute('aria-expanded', 'false');
    $('inspectButton').focus();
  }

  $('inspectButton').addEventListener('click', open);
  $('closeInspector').addEventListener('click', close);
  $('compareViewButton').addEventListener('click', () => setView(false));
  $('heatmapViewButton').addEventListener('click', () => setView(true));
  $('comparePosition').addEventListener('input', comparePosition);
  $('differenceGain').addEventListener('input', () => {
    if (mapFrame !== null) cancelAnimationFrame(mapFrame);
    mapFrame = requestAnimationFrame(() => { mapFrame = null; drawMap(); });
  });
  $('changeMap').addEventListener('keydown', (event) => {
    if (!analysis || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    pixelDetails(selectedPixel.x + (event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0),
      selectedPixel.y + (event.key === 'ArrowDown' ? 1 : event.key === 'ArrowUp' ? -1 : 0));
  });
  function updateCoordinates() {
    if (!analysis) return;
    const x = $('pixelX').valueAsNumber;
    const y = $('pixelY').valueAsNumber;
    const validX = Number.isInteger(x) && x >= 0 && x < analysis.summary.width;
    const validY = Number.isInteger(y) && y >= 0 && y < analysis.summary.height;
    $('pixelX').setAttribute('aria-invalid', String(!validX));
    $('pixelY').setAttribute('aria-invalid', String(!validY));
    if (!validX || !validY) {
      $('coordinateError').textContent = 'Enter whole numbers within the shown ranges. The last valid pixel stays selected.';
      $('coordinateError').hidden = false;
      return;
    }
    pixelDetails(x, y, false);
  }
  for (const [id, axis] of [['pixelX', 'x'], ['pixelY', 'y']]) {
    $(id).addEventListener('input', updateCoordinates);
    $(id).addEventListener('blur', () => {
      if (!analysis) return;
      const value = $(id).valueAsNumber;
      const limit = axis === 'x' ? analysis.summary.width : analysis.summary.height;
      $(id).value = Math.max(0, Math.min(limit - 1, Number.isFinite(value) ? Math.trunc(value) : selectedPixel[axis]));
      updateCoordinates();
    });
  }
  $('changeMap').addEventListener('click', (event) => {
    if (!analysis) return;
    const bounds = $('changeMap').getBoundingClientRect();
    pixelDetails((event.clientX - bounds.left) / bounds.width * analysis.summary.width,
      (event.clientY - bounds.top) / bounds.height * analysis.summary.height);
  });
  window.ChangeInspector = { reset, prepare };
  function positionFromPointer(event) {
    const bounds = $('compareStage').getBoundingClientRect();
    if (!bounds.width) return;
    $('comparePosition').value = Math.max(0, Math.min(100, Math.round((event.clientX - bounds.left) / bounds.width * 100)));
    comparePosition();
  }
  $('compareStage').addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    $('compareStage').setPointerCapture(event.pointerId);
    positionFromPointer(event);
  });
  $('compareStage').addEventListener('pointermove', (event) => {
    if ($('compareStage').hasPointerCapture(event.pointerId)) positionFromPointer(event);
  });
  for (const name of ['pointerup', 'pointercancel']) {
    $('compareStage').addEventListener(name, (event) => {
      if ($('compareStage').hasPointerCapture(event.pointerId)) $('compareStage').releasePointerCapture(event.pointerId);
    });
  }
  reset();
})();
