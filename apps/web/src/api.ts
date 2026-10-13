export const API = location.origin;
export let token =
  new URLSearchParams(location.hash.slice(1)).get('token') ||
  sessionStorage.getItem('agent-token') ||
  '';
if (token) {
  sessionStorage.setItem('agent-token', token);
  history.replaceState(null, '', location.pathname);
}
export async function request<T = unknown>(
  path: string,
  method = 'GET',
  body?: unknown,
): Promise<T> {
  const r = await fetch(API + '/api' + path, {
    method,
    headers: {
      Authorization: 'Bearer ' + token,
      ...(body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
    },
    body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
  });
  if (!r.ok) {
    let detail;
    try {
      detail = (await r.json()).detail;
    } catch {
      detail = r.statusText;
    }
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return r.json();
}

export function authenticate(value: string) {
  token = value;
  sessionStorage.setItem('agent-token', value);
}
