import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

const TOKEN_KEY = "duka_pos_token";

const client = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
});

client.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem(TOKEN_KEY);

    if (token) {
      config.headers.Authorization = `Token ${token}`;
    }

    return config;
  },
  (error) => Promise.reject(error),
);

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem("duka_pos_user");

      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }

    return Promise.reject(error);
  },
);

// DRF returns absolute "next" links built from the Host header. Keep only the
// path so axios always uses baseURL, even when the frontend is proxied.
function pagePath(url) {
  if (!url) return null;
  try {
    const parsed = new URL(url, window.location.origin);
    return `${parsed.pathname}${parsed.search}`;
  } catch {
    return url;
  }
}

export function queryString(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) {
      search.set(key, value);
    }
  });
  const value = search.toString();
  return value ? `?${value}` : "";
}

async function getAllPages(url) {
  const results = [];
  let next = url;
  let pages = 0;

  // Stop a month with thousands of rows from locking the till in a fetch loop.
  while (next && pages < 40) {
    pages += 1;
    const { data } = await client.get(pagePath(next));
    if (Array.isArray(data)) return [...results, ...data];
    results.push(...(data.results ?? []));
    next = data.next;
  }

  return results;
}

function normalizePage(data) {
  if (Array.isArray(data)) {
    return { results: data, count: data.length, next: null, previous: null };
  }
  return {
    results: Array.isArray(data?.results) ? data.results : [],
    count: Number(data?.count ?? 0),
    next: data?.next ?? null,
    previous: data?.previous ?? null,
  };
}

function productRequestData(data) {
  if (!data.image) {
    const json = { ...data };
    delete json.image;
    return json;
  }

  const formData = new FormData();

  Object.entries(data).forEach(([key, value]) => {
    if (value !== null && value !== undefined) {
      formData.append(key, value);
    }
  });

  return formData;
}

function productRequestConfig(payload) {
  return payload instanceof FormData
    ? {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      }
    : undefined;
}

export function apiErrorMessage(error, fallback) {
  const data = error?.response?.data;
  if (!data) return fallback;
  if (typeof data === "string") return data;
  if (data.detail) return data.detail;
  if (Array.isArray(data.non_field_errors)) return data.non_field_errors[0];
  for (const value of Object.values(data)) {
    if (Array.isArray(value) && value.length) return String(value[0]);
    if (typeof value === "string") return value;
  }
  return fallback;
}

export const authApi = {
  me: () => client.get("/auth/me/").then((res) => res.data),
  changePassword: (data) =>
    client.post("/auth/change-password/", data).then((res) => res.data),
};

export const shopApi = {
  info: () => client.get("/shop/").then((res) => res.data),
};

export const productsApi = {
  // Paginated catalog. Use page_size/search/category/low to keep the till fast
  // even when the shop carries thousands of products.
  list: (params) =>
    client.get(`/products/${queryString(params)}`).then((res) => normalizePage(res.data)),

  page: (url) => client.get(pagePath(url)).then((res) => normalizePage(res.data)),

  lowStock: (params) =>
    client
      .get(`/products/${queryString({ low: "1", page_size: 200, ...params })}`)
      .then((res) => normalizePage(res.data)),

  categories: (params) =>
    client.get(`/products/categories/${queryString(params)}`).then((res) => res.data),

  overview: (params) =>
    client.get(`/products/overview/${queryString(params)}`).then((res) => res.data),

  importCsv: (file, branch) => {
    const formData = new FormData();
    formData.append("file", file);
    if (branch) formData.append("branch", branch);
    return client
      .post("/products/import/", formData, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      .then((res) => res.data);
  },

  importTemplate: () =>
    client
      .get("/products/import-template/", { responseType: "blob" })
      .then((res) => res.data),

  create: (data) => {
    const payload = productRequestData(data);

    return client
      .post("/products/", payload, productRequestConfig(payload))
      .then((res) => res.data);
  },

  update: (id, data) => {
    const payload = productRequestData(data);

    return client
      .patch(`/products/${id}/`, payload, productRequestConfig(payload))
      .then((res) => res.data);
  },

  remove: (id) => client.delete(`/products/${id}/`),
};

export const salesApi = {
  list: (params) => getAllPages(`/sales/${queryString(params)}`),

  page: (url = "/sales/") =>
    client.get(pagePath(url)).then((res) => ({
      results: res.data.results ?? res.data,
      next: res.data.next ?? null,
    })),

  summary: (params) =>
    client.get(`/sales/summary/${queryString(params)}`).then((res) => res.data),

  analytics: (month, params = {}) =>
    client
      .get("/sales/analytics/", {
        params: { month, ...params },
      })
      .then((res) => res.data),

  create: (data) => client.post("/sales/", data).then((res) => res.data),

  checkout: (data, idempotencyKey) =>
    client
      .post("/sales/checkout/", data, {
        headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
      })
      .then((res) => res.data),
};

export const receiptsApi = {
  list: (params) => getAllPages(`/receipts/${queryString(params)}`),

  page: (url = "/receipts/") =>
    client.get(pagePath(url)).then((res) => normalizePage(res.data)),

  addPayment: (id, data) =>
    client.post(`/receipts/${id}/payments/`, data).then((res) => res.data),

  get: (id) => client.get(`/receipts/${id}/`).then((res) => res.data),

  credits: (params) =>
    client.get(`/receipts/credits/${queryString(params)}`).then((res) => res.data),

  stkPush: (id, data) =>
    client.post(`/receipts/${id}/stk-push/`, data).then((res) => res.data),

  exportCsv: (params) =>
    client
      .get(`/receipts/export/${queryString(params)}`, { responseType: "blob" })
      .then((res) => res.data),
};

export const expensesApi = {
  list: (params) => getAllPages(`/expenses/${queryString(params)}`),

  create: (data) => client.post("/expenses/", data).then((res) => res.data),

  update: (id, data) => client.patch(`/expenses/${id}/`, data).then((res) => res.data),

  remove: (id) => client.delete(`/expenses/${id}/`),

  summary: (params) =>
    client.get(`/expenses/summary/${queryString(params)}`).then((res) => res.data),
};

export const usersApi = {
  list: () => getAllPages("/users/"),

  create: (data) => client.post("/users/", data).then((res) => res.data),

  update: (id, data) => client.patch(`/users/${id}/`, data).then((res) => res.data),

  setPassword: (id, newPassword) =>
    client
      .post(`/users/${id}/set-password/`, { new_password: newPassword })
      .then((res) => res.data),

  deactivate: (id) => client.delete(`/users/${id}/`),
};

export const branchesApi = {
  list: () => getAllPages("/branches/"),

  create: (data) => client.post("/branches/", data).then((res) => res.data),

  update: (id, data) => client.patch(`/branches/${id}/`, data).then((res) => res.data),

  remove: (id) => client.delete(`/branches/${id}/`),
};

export const alertsApi = {
  list: (params) => getAllPages(`/alerts/${queryString(params)}`),
};

export default client;
