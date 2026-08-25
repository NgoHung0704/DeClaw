// Deep links must be line-accurate, so they pin a commit SHA rather than a
// moving branch. CI passes the deployed SHA; locally we read HEAD.
import { execFileSync } from 'node:child_process';
import { writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(here, '../..');

const sha =
  process.env.GITHUB_SHA ??
  execFileSync('git', ['rev-parse', 'HEAD'], { cwd: REPO_ROOT, encoding: 'utf8' }).trim();

writeFileSync(
  path.resolve(here, '../content/repo.json'),
  `${JSON.stringify({ owner: 'NgoHung0704', repo: 'DeClaw', sha }, null, 2)}\n`,
  'utf8',
);
console.log(`repo.json -> ${sha}`);
