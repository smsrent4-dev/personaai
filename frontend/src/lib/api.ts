import axios, {
  AxiosError,
  type InternalAxiosRequestConfig,
} from "axios";
import { useAuthStore } from "./auth-store";
/**
 * API configuration
 *
 * Local:
 *   Vite proxies /api → http://localhost:8000
 *
 * Production:
 *   VITE_API_URL should contain ONLY the backend origin, for example:
 *   https://your-backend.up.railway.app
 *
 * /api/v1 is added here automatically.
 */
// Remove trailing slashes so we never produce:
// https://backend.com//api/v1
const configuredApiUrl = (
  import.meta.env.VITE_API_URL as string | undefined
)?.replace(/\/+$/, "");
const API_BASE_URL = configuredApiUrl
  ? `${configuredApiUrl}/api/v1`
  : "/api/v1";
export const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
});
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});
let refreshInFlight: Promise<string> | null = null;
async function refreshAccessToken(): Promise<string> {
  const { refreshToken, setTokens, logout } = useAuthStore.getState();
  if (!refreshToken) {
    logout();
    throw new Error("No refresh token available");
  }
  try {
    const { data } = await axios.post(
      `${API_BASE_URL}/auth/refresh`,
      {
        refresh_token: refreshToken,
      }
    );
    setTokens(data.access_token, data.refresh_token);
    return data.access_token;
  } catch (err) {
    logout();
    throw err;
  }
}
api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as
      | (InternalAxiosRequestConfig & { _retried?: boolean })
      | undefined;
    if (
      error.response?.status === 401 &&
      original &&
      !original._retried &&
      !original.url?.includes("/auth/")
    ) {
      original._retried = true;
      try {
        refreshInFlight = refreshInFlight ?? refreshAccessToken();
        const newToken = await refreshInFlight;
        refreshInFlight = null;
        original.headers = original.headers ?? {};
        (
          original.headers as Record<string, string>
        ).Authorization = `Bearer ${newToken}`;
        return api(original);
      } catch {
        refreshInFlight = null;
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);
export function apiErrorMessage(
  err: unknown,
  fallback = "Something went wrong"
): string {
  if (axios.isAxiosError(err)) {
    const detail = (
      err.response?.data as { detail?: unknown } | undefined
    )?.detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (Array.isArray(detail) && detail[0]?.msg) {
      return String(detail[0].msg);
    }
  }
  return fallback;
}