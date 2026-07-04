// Local history of job ids launched/viewed from THIS browser. The API has no
// list-jobs endpoint, so the Jobs board uses this + the in-flight videos query.
const KEY = "katbook_recent_jobs";
const MAX = 20;

export function recentJobs(): string[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function rememberJob(id: string): void {
  const cur = recentJobs().filter((x) => x !== id);
  cur.unshift(id);
  localStorage.setItem(KEY, JSON.stringify(cur.slice(0, MAX)));
}
