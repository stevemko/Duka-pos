import { createContext, useCallback, useContext, useEffect, useState } from "react";
import client, { authApi, branchesApi, shopApi } from "../api/client";

const AuthContext = createContext(null);

const TOKEN_KEY = "duka_pos_token";
const USER_KEY = "duka_pos_user";
const BRANCH_KEY = "duka_pos_branch";
const IDLE_MINUTES = Math.max(5, Number(import.meta.env.VITE_IDLE_TIMEOUT_MINUTES || 30));

function getStoredUser() {
  try {
    const stored = localStorage.getItem(USER_KEY);
    return stored ? JSON.parse(stored) : null;
  } catch {
    return null;
  }
}

function normalizeUser(profile = {}, flags = {}) {
  return {
    ...profile,
    username: profile.username || flags.username || "",
    is_staff: Boolean(flags.is_staff ?? profile.role === "manager"),
    is_superuser: Boolean(flags.is_superuser ?? profile.is_superuser),
    can_manage: Boolean(profile.can_manage ?? flags.is_staff),
    can_manage_users: Boolean(
      profile.can_manage_users ?? flags.is_superuser ?? profile.is_superuser,
    ),
    can_view_all_branches: Boolean(profile.can_view_all_branches ?? false),
  };
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState(getStoredUser);
  const [branches, setBranches] = useState([]);
  const [shop, setShop] = useState(null);
  const [activeBranchId, setActiveBranchId] = useState(
    () => localStorage.getItem(BRANCH_KEY) || "",
  );
  const [workspaceLoading, setWorkspaceLoading] = useState(Boolean(token));

  const persistUser = useCallback((profile) => {
    localStorage.setItem(USER_KEY, JSON.stringify(profile));
    setUser(profile);
  }, []);

  const chooseDefaultBranch = useCallback((list, profile) => {
    if (!list.length) return "";
    const stored = localStorage.getItem(BRANCH_KEY);
    if (stored === "all" && profile?.can_view_all_branches) return "all";
    if (stored && list.some((branch) => branch.id === stored)) return stored;
    if (profile?.branch?.id && list.some((branch) => branch.id === profile.branch.id)) {
      return profile.branch.id;
    }
    const firstActive = list.find((branch) => branch.is_active) || list[0];
    return firstActive.id;
  }, []);

  const refreshWorkspace = useCallback(async () => {
    if (!localStorage.getItem(TOKEN_KEY)) return;
    try {
      const [profile, branchList, shopInfo] = await Promise.all([
        authApi.me(),
        branchesApi.list(),
        shopApi.info().catch(() => null),
      ]);
      const normalized = normalizeUser(profile);
      persistUser(normalized);
      setBranches(branchList);
      if (shopInfo) setShop(shopInfo);
      setActiveBranchId((current) => {
        if (current === "all" && normalized.can_view_all_branches) return current;
        const next = chooseDefaultBranch(branchList, normalized);
        localStorage.setItem(BRANCH_KEY, next);
        return next;
      });
    } catch {
      // The axios interceptor handles an expired session.
    } finally {
      setWorkspaceLoading(false);
    }
  }, [chooseDefaultBranch, persistUser]);

  useEffect(() => {
    if (token) refreshWorkspace();
  }, [token, refreshWorkspace]);

  const login = async (username, password) => {
    const response = await client.post("/auth/login/", { username, password });
    const { token: newToken, is_staff, is_superuser } = response.data;
    const profile = normalizeUser(response.data.user || {}, {
      username: response.data.username,
      is_staff,
      is_superuser,
    });

    localStorage.setItem(TOKEN_KEY, newToken);
    persistUser(profile);
    setToken(newToken);
    await refreshWorkspace();

    return profile;
  };

  const logout = useCallback(async () => {
    try {
      if (token) {
        await client.post("/auth/logout/");
      }
    } catch {
      // Even if the server request fails, clear the local session.
    } finally {
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      localStorage.removeItem(BRANCH_KEY);
      setToken(null);
      setUser(null);
      setBranches([]);
      setShop(null);
      setActiveBranchId("");
    }
  }, [token]);

  // Sign out idle terminals so an unattended till cannot be used by a passer-by.
  useEffect(() => {
    if (!token) return undefined;
    let timer;
    const reset = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => logout(), IDLE_MINUTES * 60 * 1000);
    };
    const events = ["mousemove", "mousedown", "keydown", "touchstart", "scroll"];
    events.forEach((event) => window.addEventListener(event, reset, { passive: true }));
    reset();

    return () => {
      window.clearTimeout(timer);
      events.forEach((event) => window.removeEventListener(event, reset));
    };
  }, [token, logout]);

  const setActiveBranchIdPersisted = (value) => {
    localStorage.setItem(BRANCH_KEY, value);
    setActiveBranchId(value);
  };

  const activeBranch =
    activeBranchId && activeBranchId !== "all"
      ? branches.find((branch) => branch.id === activeBranchId) || null
      : null;

  const value = {
    token,
    user,
    shop,
    branches,
    activeBranch,
    activeBranchId,
    setActiveBranchId: setActiveBranchIdPersisted,
    branchQuery: activeBranchId && activeBranchId !== "all" ? activeBranchId : "",
    workspaceLoading,
    idleMinutes: IDLE_MINUTES,
    isAuthenticated: Boolean(token),
    canManage: Boolean(user?.can_manage ?? user?.is_staff),
    canManageUsers: Boolean(user?.can_manage_users ?? user?.is_superuser),
    canViewAllBranches: Boolean(user?.can_view_all_branches),
    login,
    logout,
    refreshWorkspace,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// oxlint-disable-next-line react/only-export-components
export function useAuth() {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error("useAuth must be used inside an AuthProvider");
  }

  return context;
}
