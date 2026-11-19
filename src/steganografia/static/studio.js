'use strict';

const registry = typeof module !== 'undefined' ? require('./method-registry.js') : MethodRegistry;

function uploadConfig(method, mode = 'crypt') {
  return method?.operations?.[mode === 'crypt' ? 'embed' : 'extract']?.input || null;
}

function validateUpload(file, method, mode = 'crypt') {
  const config = uploadConfig(method, mode);
  if (!config) return 'The API does not document supported image formats for this method and mode.';
  if (!file) return 'Choose an image first.';
  const extensionMatches = config.extensions.some((extension) => file.name.toLowerCase().endsWith(extension));
  if (file.type ? file.type !== config.mime : !extensionMatches) return `Choose a ${config.format} image for this method and mode.`;
  if (!file.size) return 'This file is empty. Choose another image.';
  if (file.size > 10 * 1024 * 1024) return 'The image can be up to 10 MB.';
  return '';
}

function decodeImage(data, method) {
  const config = method?.operations?.embed?.output;
  if (!config || data.success !== true || data.method !== method.name || data.format !== config.format || typeof data.image_base64 !== 'string' || !data.image_base64) {
    throw new Error('The API did not return a valid encoded image.');
  }
  const binary = atob(data.image_base64);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  const signature = config.format === 'PNG'
    ? [137, 80, 78, 71, 13, 10, 26, 10] : [255, 216, 255];
  if (!signature.every((byte, index) => bytes[index] === byte)) throw new Error('The returned image has an unexpected format.');
  return new Blob([bytes], { type: config.mime });
}

if (typeof module !== 'undefined') module.exports = { uploadConfig, validateUpload, decodeImage };

if (typeof document !== 'undefined') {
  const $ = (id) => document.getElementById(id);
  const state = { mode: 'crypt', method: '', methods: [], loading: true, file: null, sourceUrl: null, resultUrl: null, busy: false };
  const selectedMethod = () => state.methods.find((method) => method.name === state.method);
  const selectedOperation = () => selectedMethod()?.operations[state.mode === 'crypt' ? 'embed' : 'extract'];
  const optionControls = new Map();

  function setPhase(phase) {
    const split = state.mode === 'crypt' && ['processing', 'success'].includes(phase);
    $('workspace').dataset.state = phase;
    $('workspace').classList.toggle('split', split);
    $('transferConnector').dataset.motion = phase === 'processing' ? 'animated' : 'static';
    $('resultPanel').dataset.view = phase === 'success' ? 'ready' : 'loading';
    $('resultStatus').hidden = phase !== 'processing';
    $('resultPanel').setAttribute('aria-hidden', String(!split));
    $('resultPanel').inert = !split;
  }

  function updateControls() {
    $('workspace').querySelectorAll('button, input, select, textarea').forEach((control) => { control.disabled = state.busy; });
    $('methodSelect').disabled = state.busy || state.loading || !state.methods.length;

    const operation = selectedOperation();
    $('proceedButton').disabled = state.busy || state.loading || !operation || Boolean(operation.reason);
    for (const id of ['fileInput', 'dropzone', 'changeFile']) $(id).disabled = state.busy || !uploadConfig(selectedMethod(), state.mode);
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
    const method = selectedMethod();
    const operation = selectedOperation();
    const config = uploadConfig(method, state.mode);
    const decrypt = state.mode === 'decrypt';
    $('workspace').dataset.mode = state.mode;
    $('panelTitle').textContent = decrypt ? 'Reveal text from an image' : 'Hide text in an image';
    $('panelDescription').textContent = decrypt
      ? `Upload an image and reveal its message${method ? ` with ${method.label}` : ''}.`
      : `Choose an image and hide your message${method ? ` with ${method.label}` : ''}.`;
    $('sectionKicker').textContent = decrypt ? 'Reveal information' : 'Hide information';
    $('messageField').hidden = decrypt;
    $('methodFormat').textContent = config ? `${config.format} → ${decrypt ? 'Text' : operation?.output?.format || '?'}` : 'Format unavailable';
    $('methodNotice').hidden = !method || Boolean(operation && !operation.reason);
    $('methodNotice').textContent = !method ? '' : operation?.reason ||
      `No ${decrypt ? 'extract' : 'embed'} HTTP route is documented for ${method.label}. Processing is unavailable; no other method will be used instead.`;
    $('fileInput').accept = config?.accept || '';
    $('fileStatus').textContent = state.file ? (decrypt ? 'Ready to extract' : 'Ready to encode') : config ? `${config.format} only · Up to 10 MB` : 'Upload unavailable';
    $('fileLabel').textContent = config ? `${config.format} image` : 'Carrier image';
    $('dropzoneTitle').textContent = config ? `Drop a ${config.format} image here` : 'Select a method with a supported API contract';
    document.querySelectorAll('.mode-button').forEach((tab) => {
      const active = tab.dataset.mode === state.mode;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    updateControls();
  }

  function renderOptions() {
    optionControls.clear();
    $('methodOptions').replaceChildren();
    for (const [index, option] of (selectedOperation()?.options || []).entries()) {
      const { name, schema, required, secret } = option;
      const block = document.createElement('div');
      block.className = 'field-block method-option';
      const row = document.createElement('div');
      row.className = 'field-label-row';
      const label = document.createElement('label');
      label.htmlFor = `method-option-${index}`;
      label.textContent = schema.title || name;
      const requirement = document.createElement('span');
      requirement.textContent = required ? 'Required' : 'Optional';
      row.append(label, requirement);
      const choices = schema.enum || (schema.type === 'boolean' ? [true, false] : null);
      const input = document.createElement(choices && !secret ? 'select' : 'input');
      input.id = label.htmlFor;
      input.name = name;
      input.required = required;
      input.autocomplete = 'off';
      input.spellcheck = false;
      if (choices && !secret) {
        const empty = document.createElement('option');
        empty.value = '';
        empty.textContent = required ? 'Choose a value' : 'Use server default';
        input.append(empty);
        for (const value of choices) {
          const item = document.createElement('option');
          item.value = String(value);
          item.textContent = String(value);
          input.append(item);
        }
      } else {
        input.type = secret ? 'password' : ['integer', 'number'].includes(schema.type) ? 'number' : 'text';
        if (input.type === 'number') {
          input.step = schema.type === 'integer' ? '1' : 'any';
          if (schema.minimum !== undefined) input.min = schema.minimum;
          if (schema.maximum !== undefined) input.max = schema.maximum;
        }
      }
      // Never populate a secret from metadata or persist a user's key.
      input.value = !secret && schema.default !== undefined ? String(schema.default) : '';
      if (secret && !required) input.placeholder = 'Leave empty to use the server default';
      const hint = document.createElement('p');
      hint.id = `${input.id}-hint`;
      hint.className = 'field-hint';
      hint.textContent = schema.description || (secret ? 'Use the same key to hide and reveal.' : `${schema.type} option`);
      input.setAttribute('aria-describedby', hint.id);
      input.addEventListener('input', () => { if (!state.busy) { clearResult(); renderContext(); } });
      input.addEventListener('change', () => { if (!state.busy) { clearResult(); renderContext(); } });
      optionControls.set(name, input);
      block.append(row, input, hint);
      $('methodOptions').append(block);
    }
  }

  async function loadMethods() {
    if (state.busy) return;
    state.loading = true;
    clearResult();
    optionControls.forEach((input) => { input.value = ''; });
    optionControls.clear();
    $('methodOptions').replaceChildren();
    $('registryStatus').textContent = 'Loading methods from the API…';
    $('registryStatus').hidden = false;
    updateControls();
    try {
      const result = await registry.load();
      state.methods = result.methods;
      state.method = state.methods.some((method) => method.name === state.method) ? state.method : state.methods[0]?.name || '';
      $('methodSelect').replaceChildren();
      for (const method of state.methods) {
        const option = document.createElement('option');
        option.value = method.name;
        option.textContent = method.label + (Object.keys(method.operations).length ? '' : ' — API unavailable');
        $('methodSelect').append(option);
      }
      $('methodSelect').value = state.method;
      $('registryStatus').textContent = result.warning || (state.methods.length ? '' : 'The API advertised no methods.');
    } catch (error) {
      state.methods = [];
      state.method = '';
      $('methodSelect').replaceChildren();
      $('registryStatus').textContent = error.message || 'Could not load API methods.';
    } finally {
      state.loading = false;
      $('registryStatus').hidden = !$('registryStatus').textContent;
      renderOptions();
      if (state.file && validateUpload(state.file, selectedMethod(), state.mode)) removeFile();
      renderContext();
    }
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
    const error = validateUpload(file, selectedMethod(), state.mode);
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
    const contextChanged = modeChanged || method !== state.method;
    state.mode = mode;
    state.method = method;
    clearResult();
    if (contextChanged) renderOptions();
    $('fileError').textContent = '';
    if (modeChanged || (state.file && validateUpload(state.file, selectedMethod(), mode))) removeFile();
    renderContext();
  }

  async function processImage() {
    const method = selectedMethod();
    const operation = selectedOperation();
    if (state.busy || state.loading || !operation || operation.reason) return;
    const error = validateUpload(state.file, method, state.mode);
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
    let options;
    try {
      options = registry.optionValues(operation.options, Object.fromEntries([...optionControls].map(([name, input]) => [name, input.value])));
    } catch (error) {
      clearResult();
      $('processMessage').textContent = error.message;
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
      options.forEach(([name, value]) => payload.append(name, value));
      const response = await fetch(operation.endpoint, {
        method: 'POST', body: payload, signal: AbortSignal.timeout(120000), redirect: 'error',
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(data?.error || `Request failed (${response.status}). Please try again.`);
      if (!data || data.success !== true || data.method !== method.name) throw new Error('The API returned an invalid response.');
      if (state.mode === 'crypt') {
        const blob = decodeImage(data, method);
        state.resultUrl = URL.createObjectURL(blob);
        $('resultImage').src = state.resultUrl;
        await $('resultImage').decode();
        $('resultImage').hidden = false;
        $('resultFileName').textContent = `encoded-${state.file.name.replace(/\.[^.]+$/, '')}.${operation.output.extension}`;
        $('resultFooter').hidden = false;
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

  $('stegForm').addEventListener('reset', (event) => {
    event.preventDefault();
    if (state.busy) return;
    $('secretMessage').value = '';
    $('characterCount').textContent = '0';
    renderOptions();
    removeFile();
  });
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
  loadMethods();
}
