import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_URL || "/api";

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

export function skipsAutomaticRefresh(url) {
  const path = String(url || "");
  return (
    path.includes("/auth/login")
    || path.includes("/auth/register")
    || path.includes("/auth/refresh")
    || path.includes("/auth/logout")
  );
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const request = error.config;
    if (
      error.response?.status !== 401
      || request?._retry
      || skipsAutomaticRefresh(request?.url)
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
