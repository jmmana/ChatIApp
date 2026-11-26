import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { LoginPage } from "@/features/auth/LoginPage";
import { RequireAdmin } from "@/features/auth/RequireAdmin";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { DatasourcesPage } from "@/features/datasources/DatasourcesPage";
import { IntegrationsPage } from "@/features/integrations/IntegrationsPage";
import { EmptyState } from "./EmptyState";
import { Layout } from "./Layout";
import { appRoutes } from "./routes";

const queryClient = new QueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route element={<RequireAuth />}>
              <Route element={<Layout />}>
                <Route index element={<Navigate to={appRoutes[0].path} replace />} />
                {appRoutes.map((route) => (
                  <Route
                    key={route.path}
                    path={route.path}
                    element={
                      <RequireAdminIfNeeded adminOnly={route.adminOnly}>
                        {route.path === "/integraciones" ? (
                          <IntegrationsPage />
                        ) : route.path === "/fuentes-de-datos" ? (
                          <DatasourcesPage />
                        ) : (
                          <EmptyState route={route} />
                        )}
                      </RequireAdminIfNeeded>
                    }
                  />
                ))}
                <Route path="*" element={<Navigate to={appRoutes[0].path} replace />} />
              </Route>
            </Route>
          </Routes>
        </AuthProvider>
      </TooltipProvider>
    </QueryClientProvider>
  );
}

function RequireAdminIfNeeded({
  adminOnly,
  children,
}: {
  adminOnly: boolean;
  children: ReactNode;
}) {
  return adminOnly ? <RequireAdmin>{children}</RequireAdmin> : children;
}
