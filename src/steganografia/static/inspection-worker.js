'use strict';
importScripts('/pixel-analysis.js?v=inspect1');
self.onmessage = ({ data }) => {
  try {
    const before = new Uint8ClampedArray(data.before);
    const after = new Uint8ClampedArray(data.after);
    const summary = self.PixelAnalysis.compareRgba(before, after, data.width, data.height);
    const scale = Math.min(1, 1000 / data.width, 700 / data.height);
    const previewWidth = Math.max(1, Math.round(data.width * scale));
    const previewHeight = Math.max(1, Math.round(data.height * scale));
    const previewBefore = new Uint8ClampedArray(previewWidth * previewHeight * 4);
    const previewDelta = new Uint8Array(previewWidth * previewHeight);
    for (let y = 0; y < previewHeight; y += 1) {
      for (let x = 0; x < previewWidth; x += 1) {
        const source = (Math.floor(y * data.height / previewHeight) * data.width + Math.floor(x * data.width / previewWidth)) * 4;
        previewBefore.set(before.subarray(source, source + 4), (y * previewWidth + x) * 4);
      }
    }
    for (let y = 0; y < data.height; y += 1) {
      for (let x = 0; x < data.width; x += 1) {
        const pixel = y * data.width + x;
        if (!summary.changedMask[pixel]) continue;
        const offset = pixel * 4;
        const delta = Math.max(Math.abs(before[offset] - after[offset]), Math.abs(before[offset + 1] - after[offset + 1]), Math.abs(before[offset + 2] - after[offset + 2]));
        const target = Math.floor(y * previewHeight / data.height) * previewWidth + Math.floor(x * previewWidth / data.width);
        previewDelta[target] = Math.max(previewDelta[target], delta);
      }
    }
    self.postMessage({ summary, before: before.buffer, after: after.buffer, previewWidth, previewHeight, previewBefore, previewDelta },
      [summary.changedMask.buffer, before.buffer, after.buffer, previewBefore.buffer, previewDelta.buffer]);
  } catch (error) {
    self.postMessage({ error: error.message || 'Pixel comparison failed.' });
  }
};
