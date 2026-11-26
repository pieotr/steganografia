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

function decodeFile(data) {
  if (data.payload_type !== 'file' || typeof data.filename !== 'string' || !data.filename ||
      typeof data.file_base64 !== 'string' || !Number.isSafeInteger(data.payload_length_bytes) || data.payload_length_bytes < 0) {
    throw new Error('The API did not return a valid recovered file.');
  }
  const bytes = Uint8Array.from(atob(data.file_base64), (character) => character.charCodeAt(0));
  if (bytes.length !== data.payload_length_bytes) throw new Error('The recovered file size does not match the API response.');
  // Do not render active formats (HTML/SVG/PDF) inline or trust uploaded MIME.
  const png = [137, 80, 78, 71, 13, 10, 26, 10].every((byte, index) => bytes[index] === byte);
  const jpeg = [255, 216, 255].every((byte, index) => bytes[index] === byte);
  return { blob: new Blob([bytes], { type: png ? 'image/png' : jpeg ? 'image/jpeg' : 'application/octet-stream' }),
    filename: data.filename.replace(/\\/g, '/').split('/').pop().replace(/[\x00-\x1f\x7f]/g, '') || 'recovered-file.bin', preview: png || jpeg };
}

function apiErrorMessage(data, status, mode = 'crypt') {
  // Upstream error prose is Polish and has no stable error codes. Translate
  // recognized cases here; never expose arbitrary server prose or tracebacks.
  const error = typeof data?.error === 'string' ? data.error : '';
  if (status === 413) return 'The upload is too large. Choose smaller files and try again.';
  if (status >= 500) return 'A server error prevented processing. Please try again later.';
  if (status === 404 || status === 405) return 'This API operation is unavailable. Reload the page and try again.';
  if (status === 401 || status === 403) return 'Access to this API operation was denied.';
  if (status === 429) return 'The server is busy. Wait a moment and try again.';
  const capacity = /^LENGTH \((\d+) B\) przekracza pojemność obrazu \(maksymalnie (\d+) B payloadu\)$/.exec(error);
  if (capacity || /pojemność|nie mieści nagłówka|^Obraz mieści|^Sekwencja ma|Ramka nsF5 jest dłuższa|suche współczynniki/i.test(error)) {
    if (mode === 'decrypt') return 'Hidden data does not fit this image. The image may be damaged, or the selected method or key may be incorrect.';
    if (capacity) return `The payload is too large for this image: ${capacity[1]} bytes required, ${capacity[2]} bytes available. Use a smaller message or file, or a larger carrier image.`;
    return 'The image has insufficient capacity for this payload or is too small for the header. Use a smaller message or file, or a larger carrier image.';
  }
  if (error === 'Payload nie zawiera osadzonego pliku.') return 'No hidden file was found. If the image contains text, select Text instead.';
  if (error === 'Payload nie jest poprawnym UTF-8') return 'The hidden data is not valid UTF-8 text. If it is a file, select Photo or file instead.';
  if (/histogram/i.test(error)) return 'The selected method could not preserve the JPEG histogram for this payload. Try a smaller payload or another carrier image.';
  if (/PNG|JPEG|format obrazu|odczytać obrazu|tryb obrazu|bezpiecznego rozmiaru/i.test(error)) return 'The image format or contents are unsupported. Choose a valid image in the format shown for this method.';
  if (mode === 'decrypt') return 'Could not recover the hidden content. Check the method, content type and key, and use the unchanged encoded image.';
  return 'The API could not process this image. Check the image, hidden content and method options, then try again.';
}

if (typeof module !== 'undefined') module.exports = { uploadConfig, validateUpload, decodeImage, decodeFile, apiErrorMessage };

if (typeof document !== 'undefined') {
  const $ = (id) => document.getElementById(id);
  const state = { mode: 'crypt', method: '', methods: [], loading: true, file: null, sourceUrl: null, resultUrl: null, extractedUrl: null, busy: false };
  const filePayload = () => $('payloadType').value === 'file';
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
    $('proceedButton').disabled = state.busy || state.loading || !operation || Boolean(operation.reason) || (filePayload() && !operation.filePayload);
    for (const id of ['fileInput', 'dropzone', 'changeFile']) $(id).disabled = state.busy || !uploadConfig(selectedMethod(), state.mode);
    $('proceedButton').querySelector('span').textContent = state.busy ? 'Processing…' : 'Proceed';
    $('stegForm').setAttribute('aria-busy', String(state.busy));
  }

  function clearResult() {
    window.ChangeInspector?.reset();
    window.ImageHistogram?.resetResult();
    if (state.extractedUrl) URL.revokeObjectURL(state.extractedUrl);
    state.extractedUrl = null;
    $('extractedFileBlock').hidden = true;
    $('extractedFilePreview').hidden = true;
    $('extractedFilePreview').removeAttribute('src');
    $('extractedFileName').textContent = '';
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
    const content = filePayload() ? 'a file' : 'text';
    $('panelTitle').textContent = decrypt ? `Reveal ${content} from an image` : `Hide ${content} in an image`;
    $('panelDescription').textContent = decrypt
      ? `Upload an image and recover its hidden ${filePayload() ? 'photo or file' : 'message'}${method ? ` with ${method.label}` : ''}.`
      : `Choose a carrier image and hide ${filePayload() ? 'a photo or any file' : 'your message'}${method ? ` with ${method.label}` : ''}.`;
    $('sectionKicker').textContent = decrypt ? 'Reveal information' : 'Hide information';
    $('messageField').hidden = decrypt || filePayload();
    $('payloadFileField').hidden = decrypt || !filePayload();
    $('payloadSupport').hidden = !filePayload() || Boolean(operation?.filePayload);
    $('resultTitle').textContent = filePayload() ? 'Image with a hidden file' : 'Image with a hidden message';
    $('methodFormat').textContent = config ? `${config.format} → ${decrypt ? (filePayload() ? 'File' : 'Text') : operation?.output?.format || '?'}` : 'Format unavailable';
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
    window.ImageHistogram?.reset();
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
    window.ImageHistogram?.setSource(file);
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
    if (contextChanged) $('payloadFileInput').value = '';
    $('fileError').textContent = '';
    if (modeChanged || (state.file && validateUpload(state.file, selectedMethod(), mode))) removeFile();
    renderContext();
  }

  async function processImage() {
    const method = selectedMethod();
    const operation = selectedOperation();
    if (state.busy || state.loading || !operation || operation.reason || (filePayload() && !operation.filePayload)) return;
    const error = validateUpload(state.file, method, state.mode);
    if (error) {
      $('fileError').textContent = error;
      $('dropzone').focus();
      return;
    }
    const hiddenFile = $('payloadFileInput').files?.[0];
    if (state.mode === 'crypt' && filePayload() && (!hiddenFile || hiddenFile.size > 10 * 1024 * 1024)) {
      $('processMessage').textContent = hiddenFile ? 'The hidden file can be up to 10 MB.' : 'Choose the photo or file you want to hide.';
      $('payloadFileInput').focus();
      return;
    }
    if (state.mode === 'crypt' && !filePayload() && !$('secretMessage').value.trim()) {
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
      if (state.mode === 'crypt') {
        if (filePayload()) payload.append('payload_file', hiddenFile);
        else payload.append('text', $('secretMessage').value);
      } else if (operation.filePayload) payload.append('payload_type', filePayload() ? 'file' : 'text');
      options.forEach(([name, value]) => payload.append(name, value));
      const response = await fetch(operation.endpoint, {
        method: 'POST', body: payload, signal: AbortSignal.timeout(120000), redirect: 'error',
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(apiErrorMessage(data, response.status, state.mode));
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
        window.ImageHistogram?.setResult(blob);
        $('inspectPayloadLabel').textContent = filePayload() ? 'Hidden file · bytes' : 'Message · UTF-8';
        window.ChangeInspector?.prepare({
          file: state.file, encodedBlob: blob, sourceUrl: state.sourceUrl,
          resultUrl: state.resultUrl, method: state.method,
          messageBytes: filePayload() ? hiddenFile.size : new TextEncoder().encode($('secretMessage').value).length,
        });
      } else {
        if (filePayload()) {
          const recovered = decodeFile(data);
          state.extractedUrl = URL.createObjectURL(recovered.blob);
          $('extractedFileName').textContent = recovered.filename;
          $('extractedFileBlock').hidden = false;
          if (recovered.preview) {
            $('extractedFilePreview').src = state.extractedUrl;
            $('extractedFilePreview').hidden = false;
          }
        } else {
          if (typeof data.text !== 'string') throw new Error('The API did not return extracted text.');
          $('extractedText').value = data.text;
          $('extractedBlock').hidden = false;
        }
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
  $('payloadType').addEventListener('change', () => {
    if (state.busy) return;
    $('payloadFileInput').value = '';
    clearResult();
    renderContext();
  });
  $('payloadFileInput').addEventListener('change', () => { if (!state.busy) { clearResult(); renderContext(); } });
  $('downloadExtractedFile').addEventListener('click', () => {
    if (!state.extractedUrl || state.busy) return;
    const link = document.createElement('a');
    link.href = state.extractedUrl;
    link.download = $('extractedFileName').textContent;
    link.click();
  });

  $('stegForm').addEventListener('reset', (event) => {
    event.preventDefault();
    if (state.busy) return;
    $('secretMessage').value = '';
    $('payloadFileInput').value = '';
    $('payloadType').value = 'text';
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
