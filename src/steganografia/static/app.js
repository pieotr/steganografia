const MEDIA_CONFIG = Object.freeze({
  image: {
    label: 'Images',
    noun: 'image',
    accept: 'image/png',
    hint: 'PNG only · Up to 10 MB',
    types: ['image/png'],
    extensions: ['.png'],
    maxSize: 10 * 1024 * 1024,
  },
  // audio: {
  //   label: 'Audio',
  //   noun: 'audio file',
  //   accept: 'audio/*',
  //   hint: 'Choose a supported audio file',
  //   prefix: 'audio/',
  //   extensions: ['.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac'],
  // },
  // video: {
  //   label: 'Video',
  //   noun: 'video file',
  //   accept: 'video/*',
  //   hint: 'Choose a supported video file',
  //   prefix: 'video/',
  //   extensions: ['.mp4', '.webm', '.mov', '.mkv', '.avi'],
  // },
  // text: {
  //   label: 'Text',
  //   noun: 'text file',
  //   accept: '.txt,text/plain',
  //   hint: 'TXT or plain text',
  //   types: ['text/plain'],
  //   extensions: ['.txt'],
  // },
});

function getMediaConfig(media = 'image') {
  return MEDIA_CONFIG[media] || MEDIA_CONFIG.image;
}

function deriveCryptLayout(state) {
  if (state === 'processing') return { split: true, connector: 'animated', result: 'loading' };
  if (state === 'success') return { split: true, connector: 'static', result: 'ready' };
  return { split: false, connector: 'hidden', result: 'hidden' };
}

function validateUpload(file, media = 'image') {
  const config = getMediaConfig(media);
  const fileName = file && typeof file.name === 'string' ? file.name.toLowerCase() : '';
  const fileType = file && typeof file.type === 'string' ? file.type : '';
  const accepted = file && (
    (config.types && config.types.includes(fileType))
    || (config.prefix && fileType.startsWith(config.prefix))
    || (fileName && config.extensions.some((extension) => fileName.endsWith(extension)))
  );
  if (!accepted) {
    return { valid: false, message: `Choose a supported ${config.noun}.` };
  }
  if (config.maxSize && file.size > config.maxSize) {
    return { valid: false, message: 'The file can be up to 10 MB.' };
  }
  return { valid: true };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { deriveCryptLayout, getMediaConfig, validateUpload };
}

if (typeof document !== 'undefined') {
  const elements = {
    workspace: document.querySelector('#workspace'),
    title: document.querySelector('#panelTitle'),
    description: document.querySelector('#panelDescription'),
    kicker: document.querySelector('#sectionKicker'),
    mediaType: document.querySelector('#mediaType'),
    mediaSelect: document.querySelector('#mediaSelect'),
    mediaSelectButton: document.querySelector('#mediaSelectButton'),
    mediaSelectValue: document.querySelector('#mediaSelectValue'),
    mediaSelectList: document.querySelector('#mediaSelectList'),
    mediaOptions: [...document.querySelectorAll('[data-media-option]')],
    tabs: [...document.querySelectorAll('.mode-button')],
    form: document.querySelector('#stegForm'),
    fileInput: document.querySelector('#fileInput'),
    fileLabel: document.querySelector('#fileLabel'),
    dropzone: document.querySelector('#dropzone'),
    dropzoneTitle: document.querySelector('#dropzoneTitle'),
    uploadIcons: [...document.querySelectorAll('[data-upload-icon]')],
    filePreview: document.querySelector('#filePreview'),
    previewImage: document.querySelector('#previewImage'),
    mediaPlaceholder: document.querySelector('#mediaPlaceholder'),
    mediaPlaceholderType: document.querySelector('#mediaPlaceholderType'),
    fileName: document.querySelector('#fileName'),
    fileSize: document.querySelector('#fileSize'),
    changeFile: document.querySelector('#changeFile'),
    removeFile: document.querySelector('#removeFile'),
    fileError: document.querySelector('#fileError'),
    fileStatus: document.querySelector('#fileStatus'),
    messageField: document.querySelector('#messageField'),
    secretMessage: document.querySelector('#secretMessage'),
    characterCount: document.querySelector('#characterCount'),
    extractedBlock: document.querySelector('#extractedBlock'),
    extractedText: document.querySelector('#extractedText'),
    processMessage: document.querySelector('#processMessage'),
    proceedButton: document.querySelector('#proceedButton'),
    connector: document.querySelector('#transferConnector'),
    resultPanel: document.querySelector('#resultPanel'),
    resultStatus: document.querySelector('#resultStatus b'),
    resultMessage: document.querySelector('#resultMessage'),
    resultImage: document.querySelector('#resultImage'),
    resultPlaceholder: document.querySelector('#resultPlaceholder'),
    resultTitle: document.querySelector('#resultTitle'),
    resultFooter: document.querySelector('#resultFooter'),
    resultFileName: document.querySelector('#resultFileName'),
    downloadButton: document.querySelector('#downloadButton'),
  };

  const state = { mode: 'crypt', media: 'image', phase: 'idle', file: null, objectUrl: null, resultUrl: null };
  const demoMode = new URLSearchParams(window.location.search).get('demo') === '1';

  function formatSize(bytes) {
    if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  function setPhase(phase) {
    state.phase = phase;
    elements.workspace.dataset.state = phase;
    const layout = deriveCryptLayout(phase);
    elements.workspace.classList.toggle('split', state.mode === 'crypt' && layout.split);
    elements.connector.dataset.motion = layout.connector;
    elements.resultPanel.dataset.view = layout.result;
    elements.resultPanel.setAttribute('aria-hidden', String(layout.result === 'hidden'));
  }

  function clearResult() {
    if (state.resultUrl && state.resultUrl !== state.objectUrl) URL.revokeObjectURL(state.resultUrl);
    state.resultUrl = null;
    elements.resultImage.hidden = true;
    elements.resultImage.removeAttribute('src');
    elements.resultPlaceholder.hidden = true;
    elements.resultPlaceholder.textContent = '';
    elements.resultFooter.hidden = true;
    elements.resultStatus.textContent = 'Processing';
    elements.resultMessage.textContent = `The script is preparing the encoded ${getMediaConfig(state.media).noun}…`;
    setPhase('idle');
  }

  function carrierWithArticle() {
    const noun = getMediaConfig(state.media).noun;
    return `${/^[aeiou]/i.test(noun) ? 'an' : 'a'} ${noun}`;
  }

  function renderMediaContext() {
    const config = getMediaConfig(state.media);
    const carrier = carrierWithArticle();
    const decrypt = state.mode === 'decrypt';
    elements.title.textContent = decrypt ? `Reveal text from ${carrier}` : `Hide text in ${carrier}`;
    elements.description.textContent = decrypt
      ? `Choose ${carrier} to reveal its hidden message.`
      : `Choose ${carrier} and give it a secret message.`;
    elements.fileInput.accept = config.accept;
    elements.fileLabel.textContent = `${config.label} carrier file`;
    elements.dropzoneTitle.textContent = `Drop ${carrier} here`;
    elements.fileStatus.textContent = state.file
      ? (decrypt ? 'Ready to extract' : 'Ready to encode')
      : config.hint;
    elements.resultTitle.textContent = `${config.noun.charAt(0).toUpperCase()}${config.noun.slice(1)} with a hidden message`;
    elements.resultMessage.textContent = `The script is preparing the encoded ${config.noun}…`;
  }

  function setMode(mode) {
    state.mode = mode;
    clearResult();
    elements.workspace.dataset.mode = mode;
    elements.tabs.forEach((tab) => {
      const active = tab.dataset.mode === mode;
      tab.classList.toggle('active', active);
      tab.setAttribute('aria-selected', String(active));
    });

    const decrypt = mode === 'decrypt';
    elements.kicker.textContent = decrypt ? 'Reveal information' : 'Hide information';
    elements.messageField.hidden = decrypt;
    elements.extractedBlock.hidden = true;
    elements.processMessage.textContent = '';
    renderMediaContext();
  }

  function setMedia(media) {
    state.media = media;
    removeFile();
    renderMediaContext();
  }

  function syncMediaSelect(media) {
    const config = getMediaConfig(media);
    elements.mediaType.value = media;
    elements.mediaSelectValue.textContent = config.label;
    elements.mediaOptions.forEach((option) => {
      const selected = option.dataset.mediaOption === media;
      option.setAttribute('aria-selected', String(selected));
      if (selected) elements.mediaSelectButton.setAttribute('aria-activedescendant', option.id);
    });
    elements.uploadIcons.forEach((icon) => {
      icon.hidden = icon.dataset.uploadIcon !== media;
    });
  }

  function openMediaSelect(focusSelected = false) {
    elements.mediaSelect.dataset.open = 'true';
    elements.mediaSelectButton.setAttribute('aria-expanded', 'true');
    elements.mediaSelectList.hidden = false;
    if (focusSelected) {
      const selected = elements.mediaOptions.find((option) => option.getAttribute('aria-selected') === 'true');
      selected?.focus();
    }
  }

  function closeMediaSelect(returnFocus = false) {
    elements.mediaSelect.dataset.open = 'false';
    elements.mediaSelectButton.setAttribute('aria-expanded', 'false');
    elements.mediaSelectList.hidden = true;
    if (returnFocus) elements.mediaSelectButton.focus();
  }

  function chooseMedia(media) {
    syncMediaSelect(media);
    setMedia(media);
    closeMediaSelect(true);
  }

  function showFile(file) {
    const validation = validateUpload(file, state.media);
    if (!validation.valid) {
      elements.fileError.textContent = validation.message;
      return;
    }

    if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
    state.file = file;
    state.objectUrl = URL.createObjectURL(file);
    const image = state.media === 'image';
    elements.previewImage.hidden = !image;
    elements.mediaPlaceholder.hidden = image;
    if (image) elements.previewImage.src = state.objectUrl;
    else {
      elements.previewImage.removeAttribute('src');
      elements.mediaPlaceholderType.textContent = getMediaConfig(state.media).label;
    }
    elements.fileName.textContent = file.name;
    elements.fileSize.textContent = formatSize(file.size);
    elements.dropzone.hidden = true;
    elements.filePreview.hidden = false;
    elements.fileError.textContent = '';
    elements.fileStatus.textContent = state.mode === 'decrypt' ? 'Ready to extract' : 'Ready to encode';
    elements.extractedBlock.hidden = true;
    elements.processMessage.textContent = '';
    clearResult();
  }

  function removeFile() {
    clearResult();
    if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
    state.file = null;
    state.objectUrl = null;
    elements.fileInput.value = '';
    elements.previewImage.removeAttribute('src');
    elements.previewImage.hidden = false;
    elements.mediaPlaceholder.hidden = true;
    elements.fileName.textContent = '';
    elements.fileSize.textContent = '';
    elements.filePreview.hidden = true;
    elements.dropzone.hidden = false;
    elements.fileError.textContent = '';
    elements.fileStatus.textContent = getMediaConfig(state.media).hint;
    elements.extractedBlock.hidden = true;
    elements.extractedText.value = '';
    elements.processMessage.textContent = '';
  }

  function showCryptSuccess(resultUrl, fileName) {
    state.resultUrl = resultUrl;
    const image = state.media === 'image';
    elements.resultImage.hidden = !image;
    elements.resultPlaceholder.hidden = image;
    if (image) elements.resultImage.src = resultUrl;
    else {
      const config = getMediaConfig(state.media);
      elements.resultPlaceholder.innerHTML = `<strong>${config.label}</strong><span>Encoded file ready</span>`;
    }
    elements.resultFooter.hidden = false;
    elements.resultStatus.textContent = 'Ready';
    elements.resultMessage.textContent = '';
    elements.resultFileName.textContent = fileName || `encoded-${state.file.name}`;
    setPhase('success');
  }

  async function submitCrypt() {
    if (!elements.secretMessage.value.trim()) {
      elements.processMessage.textContent = 'Enter the message you want to hide.';
      elements.secretMessage.focus();
      return;
    }

    setPhase('processing');
    elements.processMessage.textContent = demoMode ? 'Demo mode — preparing a layout preview.' : 'Sending the image to the LSB API...';

    if (demoMode) {
      await new Promise((resolve) => setTimeout(resolve, 1200));
      showCryptSuccess(state.objectUrl, `encoded-${state.file.name}`);
      return;
    }

    try {
      const payload = new FormData();
      payload.append('file', state.file);
      payload.append('text', elements.secretMessage.value);

      const response = await fetch('/api/v1/lsb/embed', { method: 'POST', body: payload });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        const message = data && data.error ? data.error : 'The image could not be encoded.';
        throw new Error(message);
      }

      const base64 = data.image_base64;
      if (!base64) throw new Error('The server did not return an image payload.');

      const binary = atob(base64);
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index);
      }
      const blob = new Blob([bytes], { type: 'image/png' });
      showCryptSuccess(URL.createObjectURL(blob), `encoded-${state.file.name}`);
    } catch (error) {
      setPhase('idle');
      elements.processMessage.textContent = error.message || 'The file could not be encoded.';
    }
  }

  async function submitDecrypt() {
    elements.fileStatus.textContent = 'Processing file';
    elements.processMessage.textContent = '';

    if (demoMode) {
      await new Promise((resolve) => setTimeout(resolve, 1200));
      elements.fileStatus.textContent = 'File processed';
      elements.extractedText.value = 'The message returned by the steganalysis module will appear here.';
      elements.extractedBlock.hidden = false;
      return;
    }

    try {
      const payload = new FormData();
      payload.append('file', state.file);

      const response = await fetch('/api/v1/lsb/extract', { method: 'POST', body: payload });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        const message = data && data.error ? data.error : 'The hidden message could not be revealed.';
        throw new Error(message);
      }

      elements.fileStatus.textContent = 'File processed';
      elements.extractedText.value = data.text || '';
      elements.extractedBlock.hidden = false;
    } catch (error) {
      elements.fileStatus.textContent = 'Ready to extract';
      elements.processMessage.textContent = error.message || 'The hidden message could not be revealed.';
    }
  }

  elements.mediaType.addEventListener('change', () => {
    syncMediaSelect(elements.mediaType.value);
    setMedia(elements.mediaType.value);
  });
  elements.mediaSelectButton.addEventListener('click', () => {
    if (elements.mediaSelectList.hidden) openMediaSelect();
    else closeMediaSelect();
  });
  elements.mediaSelectButton.addEventListener('keydown', (event) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      openMediaSelect(true);
    } else if (event.key === 'Escape') {
      closeMediaSelect();
    }
  });
  elements.mediaOptions.forEach((option, index) => {
    option.addEventListener('click', () => chooseMedia(option.dataset.mediaOption));
    option.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeMediaSelect(true);
        return;
      }
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      let nextIndex = index;
      if (event.key === 'ArrowDown') nextIndex = (index + 1) % elements.mediaOptions.length;
      if (event.key === 'ArrowUp') nextIndex = (index - 1 + elements.mediaOptions.length) % elements.mediaOptions.length;
      if (event.key === 'Home') nextIndex = 0;
      if (event.key === 'End') nextIndex = elements.mediaOptions.length - 1;
      elements.mediaOptions[nextIndex].focus();
    });
  });
  document.addEventListener('pointerdown', (event) => {
    if (!elements.mediaSelect.contains(event.target)) closeMediaSelect();
  });
  elements.tabs.forEach((tab) => tab.addEventListener('click', () => setMode(tab.dataset.mode)));
  elements.dropzone.addEventListener('click', () => elements.fileInput.click());
  elements.changeFile.addEventListener('click', () => elements.fileInput.click());
  elements.removeFile.addEventListener('click', removeFile);
  elements.fileInput.addEventListener('change', () => showFile(elements.fileInput.files[0]));
  elements.secretMessage.addEventListener('input', () => {
    elements.characterCount.textContent = elements.secretMessage.value.length;
  });

  ['dragenter', 'dragover'].forEach((eventName) => elements.dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.dropzone.classList.add('dragging');
  }));
  ['dragleave', 'drop'].forEach((eventName) => elements.dropzone.addEventListener(eventName, (event) => {
    event.preventDefault();
    elements.dropzone.classList.remove('dragging');
  }));
  elements.dropzone.addEventListener('drop', (event) => showFile(event.dataTransfer.files[0]));

  elements.form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!state.file) {
      elements.fileError.textContent = `Add ${carrierWithArticle()} first.`;
      return;
    }
    elements.proceedButton.disabled = true;
    try {
      if (state.mode === 'crypt') await submitCrypt();
      else await submitDecrypt();
    } finally {
      elements.proceedButton.disabled = false;
    }
  });

  elements.downloadButton.addEventListener('click', () => {
    if (!state.resultUrl) return;
    const link = document.createElement('a');
    link.href = state.resultUrl;
    link.download = elements.resultFileName.textContent;
    link.click();
  });

  syncMediaSelect(state.media);
  renderMediaContext();
}
