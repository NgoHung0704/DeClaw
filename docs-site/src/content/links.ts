import repo from '../../content/repo.json';

/**
 * A GitHub link pinned to a commit, not a branch.
 *
 * A branch link points at whatever the file says today, so the moment lines
 * shift the link stops meaning what the page says it means.
 */
export function githubUrl(file: string, start?: number, end?: number): string {
  const base = `https://github.com/${repo.owner}/${repo.repo}/blob/${repo.sha}/${file}`;
  if (!start) return base;
  return `${base}#L${start}${end && end !== start ? `-L${end}` : ''}`;
}

export const commitSha: string = repo.sha;
