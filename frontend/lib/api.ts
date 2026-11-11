// The only place the frontend talks to the backend. Every call uses a
// same-origin /api/* path, which Next.js rewrites to the backend (API_URL).
// Responses are snake_case on the wire and mapped to camelCase here.

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function getJson<T>(path: `/api/${string}`): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    throw new ApiError(response.status, `GET ${path} failed with ${response.status}`);
  }
  return (await response.json()) as T;
}

export interface Health {
  status: string;
}

export function getHealth(): Promise<Health> {
  return getJson<Health>("/api/health");
}
