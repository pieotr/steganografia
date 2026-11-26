'use strict';

// Discovery uses only the APIs actually exposed by server.py. Python's
// MethodMetadata is NOT published by either endpoint. Never infer a route
// from a health name, or substitute one registered algorithm for another.
const MethodRegistry = (() => {
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  const isObject = (value) => value && typeof value === 'object' && !Array.isArray(value);
  const validName = (value) => typeof value === 'string' && /^[a-z0-9][a-z0-9_-]*$/.test(value);
  const formats = {
    PNG: { format: 'PNG', mime: 'image/png', extension: 'png', extensions: ['.png'], accept: 'image/png,.png' },
    JPEG: { format: 'JPEG', mime: 'image/jpeg', extension: 'jpg', extensions: ['.jpg', '.jpeg'], accept: 'image/jpeg,.jpg,.jpeg' },
  };
  // Compatibility information verified in baseline 53897ef and upstream
  // f19b1c8 server.py; this does not determine the discovered method list.
  const legacyOutput = { lsb: 'PNG', dct: 'JPEG', 'jsteg-mf': 'JPEG', f5: 'JPEG' };
  const secretOption = (name, schema) => /key|password|secret|token/i.test(name) || schema.format === 'password' || schema.writeOnly === true;

  function resolve(document, value) {
    const seen = new Set();
    while (isObject(value) && value.$ref) {
      if (typeof value.$ref !== 'string' || !value.$ref.startsWith('#/') || seen.has(value.$ref)) return null;
      seen.add(value.$ref);
      let next = document;
      for (const part of value.$ref.slice(2).split('/')) {
        const key = part.replace(/~1/g, '/').replace(/~0/g, '~');
        if (!isObject(next) || !own(next, key)) return null;
        next = next[key];
      }
      value = next;
    }
    return isObject(value) ? value : null;
  }

  function operation(document, path, action, item, name) {
    const post = resolve(document, item)?.post;
    if (!isObject(post)) return null;
    // Accept API-local paths only, without interpolation, queries, traversal,
    // URL encoding or alternate servers. No metadata can redirect an upload.
    const server = post.servers || item?.servers || document.servers;
    if (server && (!Array.isArray(server) || !server.length || server.some((entry) => !isObject(entry) || !['/api/v1', '/api/v1/'].includes(entry.url)))) return null;
    const body = resolve(document, post.requestBody);
    const schema = resolve(document, body?.content?.['multipart/form-data']?.schema);
    const properties = schema?.properties;
    const required = Array.isArray(schema?.required) ? schema.required : [];
    let reason = '';
    const binaryPayload = resolve(document, properties?.payload_file);
    const payloadChoice = action === 'embed' && binaryPayload?.type === 'string' && binaryPayload.format === 'binary' &&
      Array.isArray(schema?.oneOf) && schema.oneOf.length === 2 &&
      schema.oneOf.every((branch) => isObject(branch) && Object.keys(branch).length === 1 && Array.isArray(branch.required) && branch.required.length === 1) &&
      schema.oneOf.some((branch) => branch.required[0] === 'text') && schema.oneOf.some((branch) => branch.required[0] === 'payload_file');
    if (!isObject(properties) || schema.type !== 'object' || schema.allOf || (schema.oneOf && !payloadChoice) || schema.anyOf || !Array.isArray(schema.required) || required.some((name) => typeof name !== 'string')) {
      reason = 'The API multipart schema is missing or unsupported.';
    }
    const file = resolve(document, properties?.file);
    const text = resolve(document, properties?.text);
    if (file?.type !== 'string' || file?.format !== 'binary' || !required.includes('file') ||
        (action === 'embed' && (text?.type !== 'string' || (!required.includes('text') && !payloadChoice)))) {
      reason = 'The API does not document the required file/text contract.';
    }
    const options = [];
    for (const [key, raw] of Object.entries(properties || {})) {
      if (key === 'file' || (action === 'embed' && (key === 'text' || (key === 'payload_file' && payloadChoice))) ||
          (action === 'extract' && key === 'payload_type' && raw?.type === 'string' && Array.isArray(raw.enum) && raw.enum.includes('text') && raw.enum.includes('file'))) continue;
      const field = resolve(document, raw);
      if (!field || !['string', 'integer', 'number', 'boolean'].includes(field.type) || field.format === 'binary' || field.oneOf || field.anyOf || field.allOf || field.nullable || field.readOnly ||
          (field.enum && (!Array.isArray(field.enum) || !field.enum.length || field.enum.some((v) => typeof v !== (['integer', 'number'].includes(field.type) ? 'number' : field.type))))) {
        reason = `The API option “${key}” has an unsupported schema.`;
        continue;
      }
      options.push({ name: key, schema: field, required: required.includes(key), secret: secretOption(key, field) });
    }
    if (required.some((key) => !own(properties || {}, key))) reason = 'The API required fields are not fully documented.';
    // Optional future OpenAPI extension, NOT current backend metadata:
    // operation["x-steganography"] = {input_format:"PNG",output_format:"JPEG"}.
    // Unknown methods fail closed without an explicit supported format contract.
    const metadata = post['x-steganography'];
    const inputFormat = metadata?.input_format || (own(legacyOutput, name) ? (action === 'embed' ? 'PNG' : legacyOutput[name]) : null);
    const outputFormat = metadata?.output_format || (own(legacyOutput, name) ? legacyOutput[name] : null);
    const input = typeof inputFormat === 'string' && own(formats, inputFormat) ? formats[inputFormat] : null;
    const output = typeof outputFormat === 'string' && own(formats, outputFormat) ? formats[outputFormat] : null;
    if (!input || (action === 'embed' && !output)) reason = reason || 'The API does not document supported image formats for this method.';
    const filePayload = action === 'embed' ? Boolean(payloadChoice) : properties?.payload_type?.enum?.includes('file') === true;
    return { endpoint: path.startsWith('/api/v1/') ? path : `/api/v1${path}`, action, options, input: input || null, output: output || null, filePayload, reason };
  }

  function discover(health, document) {
    const methods = new Map();
    if (health && (!Array.isArray(health.methods) || health.methods.some((name) => !validName(name)))) throw new Error('Invalid health method list.');
    for (const name of health?.methods || []) methods.set(name, { name, label: name, operations: Object.create(null) });
    if (document) {
      if (!isObject(document.paths)) throw new Error('Invalid OpenAPI document.');
      for (const [path, item] of Object.entries(document.paths)) {
        const match = /^(?:\/api\/v1)?\/([a-z0-9][a-z0-9_-]*)\/(embed|extract)$/.exec(path);
        if (!match) continue;
        const [, name, action] = match;
        const route = operation(document, path, action, item, name);
        if (!route) continue;
        if (!methods.has(name)) methods.set(name, { name, label: name, operations: Object.create(null) });
        methods.get(name).operations[action] = route;
      }
    }
    return [...methods.values()];
  }

  async function load(fetcher = fetch) {
    const results = await Promise.allSettled(['/api/v1/health', '/api/v1/openapi.json'].map(async (url) => {
      const response = await fetcher(url, { headers: { Accept: 'application/json' }, cache: 'no-store', signal: AbortSignal.timeout(15000), redirect: 'error' });
      if (!response.ok) throw new Error(`${url.endsWith('health') ? 'Health' : 'OpenAPI'} request failed (${response.status}).`);
      const value = await response.json();
      if (!isObject(value)) throw new Error('Invalid API discovery response.');
      if (url.endsWith('health')) discover(value, null);
      else discover(null, value);
      return value;
    }));
    const value = (index) => results[index].status === 'fulfilled' ? results[index].value : null;
    return {
      methods: discover(value(0), value(1)),
      warning: results.filter((result) => result.status === 'rejected').map((result) => result.reason.message || 'API discovery failed.').join(' '),
    };
  }

  function optionValues(options, values) {
    const result = [];
    for (const option of options) {
      const { name, schema, required } = option;
      const raw = values[name];
      if (raw === undefined || raw === '') {
        if (required) throw new Error(`Enter ${name}.`);
        continue; // Omit optional fields so the server applies its defaults.
      }
      let value = raw;
      if (schema.type === 'boolean') {
        if (![true, false, 'true', 'false'].includes(raw)) throw new Error(`${name} must be true or false.`);
        value = raw === true || raw === 'true';
      } else if (schema.type === 'integer' || schema.type === 'number') {
        if ((typeof raw !== 'number' && (typeof raw !== 'string' || !raw.trim())) || typeof raw === 'boolean') throw new Error(`${name} must be a number.`);
        value = Number(raw);
        if (!Number.isFinite(value) || (schema.type === 'integer' && !Number.isSafeInteger(value))) throw new Error(`${name} must be ${schema.type === 'integer' ? 'an integer' : 'a number'}.`);
        if ((schema.minimum !== undefined && value < schema.minimum) || (schema.maximum !== undefined && value > schema.maximum) ||
            (schema.exclusiveMinimum === true && value === schema.minimum) || (schema.exclusiveMaximum === true && value === schema.maximum)) throw new Error(`${name} is outside the allowed range.`);
      } else {
        if (typeof value !== 'string') throw new Error(`${name} must be text.`);
        if ((schema.minLength !== undefined && [...value].length < schema.minLength) || (schema.maxLength !== undefined && [...value].length > schema.maxLength)) throw new Error(`${name} has an invalid length.`);
      }
      if (schema.enum && !schema.enum.includes(value)) throw new Error(`Choose an allowed value for ${name}.`);
      result.push([name, String(value)]);
    }
    return result;
  }

  return { discover, load, optionValues, secretOption };
})();
if (typeof module !== 'undefined') module.exports = MethodRegistry;
