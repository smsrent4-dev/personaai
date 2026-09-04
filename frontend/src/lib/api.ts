import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";
import { useAuthStore } from "./auth-store";

export const api = axios.create({
  baseURL: "/api/v1",
  headers: { "Content-Type": "application/json" },
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
    const { data } = await axios.post("/api/v1/auth/refresh", { refresh_token: refreshToken });
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
    const original = error.config as InternalAxiosRequestConfig & { _retried?: boolean };
    if (error.response?.status === 401 && original && !original._retried && !original.url?.includes("/auth/")) {
      original._retried = true;
      try {
        refreshInFlight = refreshInFlight ?? refreshAccessToken();
        const newToken = await refreshInFlight;
        refreshInFlight = null;
        original.headers = original.headers ?? {};
        (original.headers as Record<string, string>).Authorization = `Bearer ${newToken}`;
        return api(original);
      } catch {
        refreshInFlight = null;
        window.location.href = "/login";
      }
    }
    return Promise.reject(error);
  }
);

export function apiErrorMessage(err: unknown, fallback = "Something went wrong"): string {
  if (axios.isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  }
  return fallback;
}
