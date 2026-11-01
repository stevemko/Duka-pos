import { BrowserRouter, Navigate, Outlet, Route, Routes, Link } from "react-router-dom";

import { AuthProvider, useAuth } from "./auth/AuthContext";
import ProtectedRoute from "./auth/ProtectedRoute";

import Layout from "./components/Layout";
import { Button, EmptyState, Spinner } from "./components/ui";

import LoginScreen from "./pages/LoginScreen";
import SalesScreen from "./pages/SalesScreen";
import InventoryScreen from "./pages/InventoryScreen";
import DashboardScreen from "./pages/DashboardScreen";
import TransactionsScreen from "./pages/TransactionsScreen";
import CreditScreen from "./pages/CreditScreen";
import ExpensesScreen from "./pages/ExpensesScreen";
import TeamScreen from "./pages/TeamScreen";

function ManagerRoute() {
  const { canManage, workspaceLoading } = useAuth();

  if (workspaceLoading) {
    return <Spinner label="Checking your access" />;
  }

  if (!canManage) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
}

function NotFoundScreen() {
  return (
    <div className="rounded-2xl border border-ink-200/70 bg-white shadow-card">
      <EmptyState
        icon="search"
        title="Page not found"
        message="The page you requested does not exist or has moved."
        action={
          <Link to="/">
            <Button icon="cart">Back to the till</Button>
          </Link>
        }
      />
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginScreen />} />

          <Route element={<ProtectedRoute />}>
            <Route element={<Layout />}>
              <Route path="/" element={<SalesScreen />} />
              <Route path="/transactions" element={<TransactionsScreen />} />
              <Route path="/credit" element={<CreditScreen />} />
              <Route path="/inventory" element={<InventoryScreen />} />
              <Route path="/dashboard" element={<DashboardScreen />} />
              <Route path="*" element={<NotFoundScreen />} />

              <Route element={<ManagerRoute />}>
                <Route path="/expenses" element={<ExpensesScreen />} />
                <Route path="/team" element={<TeamScreen />} />
              </Route>
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
