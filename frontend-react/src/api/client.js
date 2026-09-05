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


api.interceptors.request.use(
    (config) => {
        const token = localStorage.getItem("access_token");

        if (token) {
            config.headers.Authorization = `Bearer ${token}`;
        }

        return config;
    }
);

let refreshPromise = null;

async function refreshAccessToken() {
    if (!refreshPromise) {
        refreshPromise = api.post("/auth/refresh").then(({ data }) => {
            localStorage.setItem("access_token", data.access_token);
            if (data.id_token) localStorage.setItem("id_token", data.id_token);
            return data.access_token;
        }).finally(() => {
            refreshPromise = null;
        });
    }
    return refreshPromise;
}

api.interceptors.response.use(
    (response) => response,
    async (error) => {
        const request = error.config;
        if (error.response?.status !== 401 || request?._retry || request?.url?.includes("/auth/")) {
            return Promise.reject(error);
        }
        request._retry = true;
        try {
            const token = await refreshAccessToken();
            request.headers.Authorization = `Bearer ${token}`;
            return api(request);
        } catch {
            localStorage.removeItem("access_token");
            localStorage.removeItem("id_token");
            localStorage.removeItem("refresh_token");
            return Promise.reject(error);
        }
    },
);


export default api;