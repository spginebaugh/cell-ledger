const LAST = "cl-last-session";

export function rememberSession(id: string) {
  try {
    localStorage.setItem(LAST, id);
  } catch {
    // ignore
  }
}

export function lastSession(): string | null {
  try {
    return localStorage.getItem(LAST);
  } catch {
    return null;
  }
}

export function forgetSession() {
  try {
    localStorage.removeItem(LAST);
  } catch {
    // ignore
  }
}
