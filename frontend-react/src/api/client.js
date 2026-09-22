import axios from "axios";

// Feature flag: if USE_NEW_BACKEND=true, use REEMPLAZAR_API_BASE; else use legacy VITE_API_URL
const USE_NEW_BACKEND = import.meta.env.VITE_USE_NEW_BACKEND === "true";
const BASE_URL = USE_NEW_BACKEND
  ? import.meta.env.REEMPLAZAR_API_BASE
  : import.meta.env.VITE_API_URL;

const api = axios.create({
  baseURL: BASE_URL,
  withCredentials: true,
});

let accessToken = null;
let refreshPromise = null;

export function setAccessToken(token) {
  accessToken = typeof token === "string" && token ? token : null;
}

export function getAccessToken() {
  return accessToken;
}

export function clearAccessToken() {
  accessToken = null;
}

api.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

export async function refreshAccessToken() {
  if (!refreshPromise) {
    refreshPromise = api
      .post("/auth/refresh")
      .then(({ data }) => {
        if (!data?.access_token) {
          throw new Error("Refresh response did not include an access token.");
        }
        setAccessToken(data.access_token);
        return data.access_token;
      })
      .catch((error) => {
        clearAccessToken();
        throw error;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const request = error.config;
    if (
      error.response?.status !== 401
      || request?._retry
      || request?.url?.includes("/auth/")
    ) {
      return Promise.reject(error);
    }

    request._retry = true;
    try {
      const token = await refreshAccessToken();
      request.headers.Authorization = `Bearer ${token}`;
      return api(request);
    } catch {
      clearAccessToken();
      return Promise.reject(error);
    }
  },
);

export default api;
