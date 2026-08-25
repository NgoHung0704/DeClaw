import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(here, '../../..');
export const CONTENT_DIR = path.resolve(here, '../../content');

/** Repo-root-relative POSIX path -> absolute OS path. */
export function repoPath(file: string): string {
  return path.resolve(REPO_ROOT, file);
}

export function repoFileExists(file: string): boolean {
  return existsSync(repoPath(file));
}

/** Lines of a repo file, CRLF normalised, 0-indexed array. */
export function readRepoLines(file: string): string[] {
  return readFileSync(repoPath(file), 'utf8').replace(/\r\n/g, '\n').split('\n');
}

/** Inclusive 1-indexed line range, joined with LF, no trailing newline. */
export function sliceLines(file: string, start: number, end: number): string {
  return readRepoLines(file).slice(start - 1, end).join('\n');
}

/** Every git-tracked file, as repo-root-relative POSIX paths. */
export function gitTrackedFiles(): string[] {
  const out = execFileSync('git', ['ls-files'], { cwd: REPO_ROOT, encoding: 'utf8' });
  return out.split('\n').filter(Boolean).map((p) => p.replace(/\\/g, '/'));
}

export type ContentFile = { name: string; json: unknown };

/** Every content JSON, including details/*.json, named by relative path. */
export function allContentFiles(): ContentFile[] {
  const files: ContentFile[] = [];
  const walk = (dir: string, prefix: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        walk(path.join(dir, entry.name), `${prefix}${entry.name}/`);
      } else if (entry.name.endsWith('.json')) {
        const raw = readFileSync(path.join(dir, entry.name), 'utf8');
        files.push({ name: `${prefix}${entry.name}`, json: JSON.parse(raw) });
      }
    }
  };
  walk(CONTENT_DIR, '');
  return files;
}

export type PathRef = { file: string; start?: number; end?: number; where: string };

/** Every object anywhere in the content tree that carries a `file` field. */
export function collectPathRefs(json: unknown, where = ''): PathRef[] {
  const refs: PathRef[] = [];
  const visit = (node: unknown, trail: string) => {
    if (Array.isArray(node)) {
      node.forEach((item, i) => visit(item, `${trail}[${i}]`));
      return;
    }
    if (node && typeof node === 'object') {
      const rec = node as Record<string, unknown>;
      if (typeof rec.file === 'string') {
        refs.push({
          file: rec.file,
          start: typeof rec.start === 'number' ? rec.start : undefined,
          end: typeof rec.end === 'number' ? rec.end : undefined,
          where: `${where}${trail}`,
        });
      }
      for (const [key, value] of Object.entries(rec)) visit(value, `${trail}.${key}`);
    }
  };
  visit(json, '');
  return refs;
}
