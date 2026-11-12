(function (root, factory) {
  'use strict';
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.PixelAnalysis = factory();
  }
}(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  var MAX_PIXELS = 4000000;
  var bitCounts = new Uint8Array(256);
  for (var value = 1; value < bitCounts.length; value += 1) {
    bitCounts[value] = bitCounts[value >>> 1] + (value & 1);
  }

  /**
   * Compare full-resolution browser-decoded RGBA buffers without mutating them.
   * Alpha is explicitly ignored. Metrics describe decoded RGB channel values,
   * not original file bytes, embedded payload bits, or proof of steganography.
   * firstChanged uses zero-based coordinates in row-major order.
   */
  function compareRgba(before, after, width, height) {
    if (!Number.isInteger(width) || !Number.isInteger(height) || width <= 0 || height <= 0) {
      throw new RangeError('width and height must be positive integers.');
    }
    var totalPixels = width * height;
    if (totalPixels > MAX_PIXELS) {
      throw new RangeError('Image must contain at most 4000000 pixels.');
    }
    if (!(before instanceof Uint8Array) && !(before instanceof Uint8ClampedArray)) {
      throw new TypeError('before must be a Uint8Array or Uint8ClampedArray RGBA buffer.');
    }
    if (!(after instanceof Uint8Array) && !(after instanceof Uint8ClampedArray)) {
      throw new TypeError('after must be a Uint8Array or Uint8ClampedArray RGBA buffer.');
    }
    var expectedLength = totalPixels * 4;
    if (before.length !== expectedLength) {
      throw new RangeError('before length must be exactly ' + expectedLength + ' RGBA entries (width * height * 4).');
    }
    if (after.length !== expectedLength) {
      throw new RangeError('after length must be exactly ' + expectedLength + ' RGBA entries (width * height * 4).');
    }
    var changedMask = new Uint8Array(totalPixels);
    var changedPixels = 0;
    var changedChannels = 0;
    var flippedBits = 0;
    var channelChanged = [0, 0, 0];
    var outsideLsbChannels = 0;
    var firstChanged = null;

    for (var pixel = 0; pixel < totalPixels; pixel += 1) {
      var offset = pixel * 4;
      var pixelChanged = false;
      for (var channel = 0; channel < 3; channel += 1) {
        var xor = before[offset + channel] ^ after[offset + channel];
        if (xor !== 0) {
          pixelChanged = true;
          changedChannels += 1;
          channelChanged[channel] += 1;
          flippedBits += bitCounts[xor];
          if ((xor & 254) !== 0) outsideLsbChannels += 1;
        }
      }
      if (pixelChanged) {
        changedMask[pixel] = 1;
        changedPixels += 1;
        if (firstChanged === null) {
          firstChanged = { x: pixel % width, y: Math.floor(pixel / width) };
        }
      }
    }

    return {
      width: width, height: height, totalPixels: totalPixels,
      changedPixels: changedPixels, changedChannels: changedChannels,
      flippedBits: flippedBits, channelChanged: channelChanged,
      outsideLsbChannels: outsideLsbChannels, changedMask: changedMask,
      firstChanged: firstChanged
    };
  }

  return { compareRgba: compareRgba, MAX_PIXELS: MAX_PIXELS };
}));
