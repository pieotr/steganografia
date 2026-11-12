'use strict';

// DCTMethod inherits JStegMethod unchanged in the supplied Python backend.
// Registry entries are not HTTP routes: do not silently substitute MF or F5.
const METHODS = Object.freeze({
  lsb: { label: 'LSB', endpoint: 'lsb', format: 'PNG', mime: 'image/png', extension: 'png' },
  jsteg: { label: 'JSteg', endpoint: 'dct', format: 'JPEG', mime: 'image/jpeg', extension: 'jpg' },
  'jsteg-mf': { label: 'JSteg-MF', endpoint: null, format: 'JPEG' },
  f5: { label: 'F5', endpoint: null, format: 'JPEG' },
});

function uploadConfig(method = 'lsb', mode = 'crypt') {
  const jpeg = mode === 'decrypt' && method !== 'lsb';
  return jpeg
    ? { accept: 'image/jpeg,.jpg,.jpeg', mime: 'image/jpeg', extensions: ['.jpg', '.jpeg'], format: 'JPEG' }
    : { accept: 'image/png,.png', mime: 'image/png', extensions: ['.png'], format: 'PNG' };
}

function validateUpload(file, method = 'lsb', mode = 'crypt') {
  const config = uploadConfig(method, mode);
  if (!file) return 'Choose an image first.';
  const extensionMatches = config.extensions.some((extension) => file.name.toLowerCase().endsWith(extension));
  if (file.type ? file.type !== config.mime : !extensionMatches) return `Choose a ${config.format} image for this method and mode.`;
  if (!file.size) return 'This file is empty. Choose another image.';
  if (file.size > 10 * 1024 * 1024) return 'The image can be up to 10 MB.';
  return '';
}

function decodeImage(data, method) {
  const config = METHODS[method];
  if (data.success !== true || data.format !== config.format || typeof data.image_base64 !== 'string' || !data.image_base64) {
    throw new Error('The API did not return a valid encoded image.');
  }
  const binary = atob(data.image_base64);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  const signature = config.format === 'PNG'
    ? [137, 80, 78, 71, 13, 10, 26, 10] : [255, 216, 255];
  if (!signature.every((byte, index) => bytes[index] === byte)) throw new Error('The returned image has an unexpected format.');
  return new Blob([bytes], { type: config.mime });
}

if (typeof module !== 'undefined') module.exports = { METHODS, uploadConfig, validateUpload, decodeImage };

if (typeof document !== 'undefined') {
  const $ = (id) => document.getElementById(id);
  const state = { mode: 'crypt', method: 'lsb', file: null, sourceUrl: null, resultUrl: null, busy: false };
  const controls = [...$('workspace').querySelectorAll('button, input, select, textarea')];

  function setPhase(phase) {
    const split = state.mode === 'crypt' && ['processing', 'success'].includes(phase);
    $('workspace').dataset.state = phase;
    $('workspace').classList.toggle('split', split);
    $('transferConnector').dataset.motion = phase === 'processing' ? 'animated' : 'static';
    $('resultPanel').dataset.view = phase === 'success' ? 'ready' : 'loading';
    $('resultPanel').setAttribute('aria-hidden', String(!split));
    $('resultPanel').inert = !split;
  }

  function updateControls() {
    controls.forEach((control) => { control.disabled = state.busy; });
    $('proceedButton').disabled = state.busy || !METHODS[state.method].endpoint;
    $('proceedButton').querySelector('span').textContent = state.busy ? 'Processing…' : 'Proceed';
    $('stegForm').setAttribute('aria-busy', String(state.busy));
  }

  function clearResult() {
    window.ChangeInspector?.reset();
    if (state.resultUrl) URL.revokeObjectURL(state.resultUrl);
    state.resultUrl = null;
    $('resultImage').hidden = true;
    $('resultImage').removeAttribute('src');
    $('resultFooter').hidden = true;
    $('resultStatus').querySelector('b').textContent = 'Processing';
    $('resultMessage').textContent = 'Preparing your encoded image…';
    $('extractedBlock').hidden = true;
    $('extractedText').value = '';
    $('processMessage').textContent = '';
    setPhase('idle');
  }

  function renderContext() {
    const method = METHODS[state.method];
    const config = uploadConfig(state.method, state.mode);
    const decrypt = state.mode === 'decrypt';
    $('workspace').dataset.mode = state.mode;
    $('panelTitle').textContent = decrypt ? 'Reveal text from an image' : 'Hide text in an image';
    $('panelDescription').textContent = decrypt
      ? `Upload a ${config.format} image and reveal its message with ${method.label}.`
      : `Choose a PNG image and hide your message with ${method.label}.`;
    $('sectionKicker').textContent = decrypt ? 'Reveal information' : 'Hide information';
    $('messageField').hidden = decrypt;
    $('keyField').hidden = state.method !== 'f5';
    $('methodFormat').textContent = decrypt ? `${method.format} → Text` : `PNG → ${method.format}`;
    $('methodNotice').hidden = Boolean(method.endpoint);
    $('methodNotice').textContent = method.endpoint ? ''
      : `${method.label} exists in the Python/CLI code, but has no HTTP endpoint in this backend. Processing is unavailable; no other method will be used instead.`;
    $('fileInput').accept = config.accept;
    $('fileStatus').textContent = state.file ? (decrypt ? 'Ready to extract' : 'Ready to encode') : `${config.format} only · Up to 10 MB`;
    $('fileLabel').textContent = `${config.format} image`;
    $('dropzoneTitle').textContent = `Drop a ${config.format} image here`;
    document.querySelectorAll('.mode-button').forEach((tab) => {
      const active = tab.dataset.mode === state.mode;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    updateControls();
  }

  function removeFile() {
    if (state.busy) return;
    clearResult();
    if (state.sourceUrl) URL.revokeObjectURL(state.sourceUrl);
    state.file = null;
    state.sourceUrl = null;
    $('fileInput').value = '';
    $('previewImage').removeAttribute('src');
    $('fileName').textContent = '';
    $('fileSize').textContent = '';
    $('filePreview').hidden = true;
    $('dropzone').hidden = false;
    $('fileError').textContent = '';
    renderContext();
  }

  function showFile(file) {
    if (state.busy || !file) return;
    const error = validateUpload(file, state.method, state.mode);
    if (error) {
      $('fileError').textContent = error;
      $('fileInput').value = '';
      return;
    }
    removeFile();
    state.file = file;
    state.sourceUrl = URL.createObjectURL(file);
    $('previewImage').src = state.sourceUrl;
    $('fileName').textContent = file.name;
    $('fileSize').textContent = file.size < 1024 * 1024
      ? `${Math.max(1, Math.round(file.size / 1024))} KB` : `${(file.size / 1024 / 1024).toFixed(1)} MB`;
    $('filePreview').hidden = false;
    $('dropzone').hidden = true;
    renderContext();
  }

  function changeContext(mode, method) {
    if (state.busy) return;
    const modeChanged = mode !== state.mode;
    if (method !== state.method) $('f5Key').value = '';
    state.mode = mode;
    state.method = method;
    clearResult();
    $('fileError').textContent = '';
    if (modeChanged || (state.file && validateUpload(state.file, method, mode))) removeFile();
    renderContext();
  }

  async function processImage() {
    const method = METHODS[state.method];
    if (state.busy || !method.endpoint) return;
    const error = validateUpload(state.file, state.method, state.mode);
    if (error) {
      $('fileError').textContent = error;
      $('dropzone').focus();
      return;
    }
    if (state.mode === 'crypt' && !$('secretMessage').value.trim()) {
      $('processMessage').textContent = 'Enter the message you want to hide.';
      $('secretMessage').focus();
      return;
    }
    clearResult();
    state.busy = true;
    updateControls();
    setPhase('processing');
    $('fileStatus').textContent = 'Processing image…';
    try {
      const payload = new FormData();
      payload.append('file', state.file);
      if (state.mode === 'crypt') payload.append('text', $('secretMessage').value);
      // F5 has no HTTP contract yet, so its key is deliberately not transmitted.
      const action = state.mode === 'crypt' ? 'embed' : 'extract';
      const response = await fetch(`/api/v1/${method.endpoint}/${action}`, {
        method: 'POST', body: payload, signal: AbortSignal.timeout(120000),
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(data?.error || `Request failed (${response.status}). Please try again.`);
      if (!data || data.success !== true) throw new Error('The API returned an invalid response.');
      if (state.mode === 'crypt') {
        const blob = decodeImage(data, state.method);
        state.resultUrl = URL.createObjectURL(blob);
        $('resultImage').src = state.resultUrl;
        await $('resultImage').decode();
        $('resultImage').hidden = false;
        $('resultFileName').textContent = `encoded-${state.file.name.replace(/\.[^.]+$/, '')}.${method.extension}`;
        $('resultFooter').hidden = false;
        $('resultStatus').querySelector('b').textContent = 'Ready';
        $('resultMessage').textContent = '';
        window.ChangeInspector?.prepare({
          file: state.file, encodedBlob: blob, sourceUrl: state.sourceUrl,
          resultUrl: state.resultUrl, method: state.method,
          messageBytes: new TextEncoder().encode($('secretMessage').value).length,
        });
      } else {
        if (typeof data.text !== 'string') throw new Error('The API did not return extracted text.');
        $('extractedText').value = data.text;
        $('extractedBlock').hidden = false;
      }
      setPhase('success');
      $('fileStatus').textContent = 'Image processed';
    } catch (error) {
      clearResult();
      setPhase('error');
      $('fileStatus').textContent = state.mode === 'crypt' ? 'Ready to encode' : 'Ready to extract';
      $('processMessage').textContent = error.name === 'TimeoutError'
        ? 'Processing timed out. Try a smaller image or retry.'
        : error.message || 'Could not reach the API. Check your connection and retry.';
    } finally {
      state.busy = false;
      updateControls();
    }
  }

  $('methodSelect').addEventListener('change', () => changeContext(state.mode, $('methodSelect').value));
  const tabs = [...document.querySelectorAll('.mode-button')];
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => changeContext(tab.dataset.mode, state.method));
    tab.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[1] : tabs[1 - index];
      changeContext(next.dataset.mode, state.method);
      next.focus();
    });
  });
  $('stegForm').addEventListener('submit', (event) => { event.preventDefault(); processImage(); });
  $('dropzone').addEventListener('click', () => $('fileInput').click());
  $('changeFile').addEventListener('click', () => $('fileInput').click());
  $('removeFile').addEventListener('click', removeFile);
  $('fileInput').addEventListener('change', () => showFile($('fileInput').files[0]));
  $('secretMessage').addEventListener('input', () => {
    $('characterCount').textContent = [...$('secretMessage').value].length;
    clearResult();
    renderContext();
  });
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach((name) => {
    $('dropzone').addEventListener(name, (event) => {
      event.preventDefault();
      $('dropzone').classList.toggle('dragging', !state.busy && ['dragenter', 'dragover'].includes(name));
      if (name === 'drop') showFile(event.dataTransfer.files[0]);
    });
  });
  $('downloadButton').addEventListener('click', () => {
    if (!state.resultUrl || state.busy) return;
    const link = document.createElement('a');
    link.href = state.resultUrl;
    link.download = $('resultFileName').textContent;
    link.click();
  });
  clearResult();
  renderContext();
}
