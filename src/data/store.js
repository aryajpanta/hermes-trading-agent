import fs from 'fs';
import path from 'path';
import getConfig from '../config/index.js';

const config = getConfig();

/**
 * File-based JSON store — each dataset is a JSON file.
 * This keeps data readable by Hermes Agent for review/analysis.
 */
const stores = {};

function storePath(name) {
  return path.join(config.dataDir, `${name}.json`);
}

function ensureDir(filePath) {
  const dir = path.dirname(filePath);
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

export function read(name) {
  const filePath = storePath(name);
  try {
    const raw = fs.readFileSync(filePath, 'utf-8');
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function write(name, data) {
  const filePath = storePath(name);
  ensureDir(filePath);
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2));
  return data;
}

export function append(name, entry) {
  const existing = read(name) || [];
  existing.push({
    ...entry,
    _timestamp: entry._timestamp || new Date().toISOString(),
  });
  return write(name, existing);
}

export function readCollection(name) {
  const dir = path.join(config.dataDir, name);
  if (!fs.existsSync(dir)) return [];
  const files = fs.readdirSync(dir).filter(f => f.endsWith('.json')).sort();
  return files.map(f => ({
    ...JSON.parse(fs.readFileSync(path.join(dir, f), 'utf-8')),
    _file: f,
  }));
}

export function writeFile(subpath, data) {
  const filePath = path.join(config.dataDir, subpath);
  ensureDir(filePath);
  const content = typeof data === 'string' ? data : JSON.stringify(data, null, 2);
  fs.writeFileSync(filePath, content);
  return filePath;
}

export function readFile(subpath) {
  const filePath = path.join(config.dataDir, subpath);
  try {
    return fs.readFileSync(filePath, 'utf-8');
  } catch {
    return null;
  }
}

export function listDir(subpath) {
  const dir = path.join(config.dataDir, subpath);
  try {
    return fs.readdirSync(dir).filter(f => !f.startsWith('.'));
  } catch {
    return [];
  }
}

export default { read, write, append, readCollection, writeFile, readFile, listDir };
