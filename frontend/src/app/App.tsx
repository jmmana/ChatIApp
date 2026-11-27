import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AuditPage } from "@/features/admin/audit/AuditPage";
import { UsersPage } from "@/features/admin/users/UsersPage";
import { AuthProvider } from "@/features/auth/AuthProvider";
import { LoginPage } from "@/features/auth/LoginPage";
import { RequireAuth } from "@/features/auth/RequireAuth";
import { DatasourcesPage } from "@/features/datasources/DatasourcesPage";
import { IntegrationsPage } from "@/features/integrations/IntegrationsPage";
import { ProvidersPage } from "@/features/providers/ProvidersPage";
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
                      route.path === "/integraciones" ? (
                        <IntegrationsPage />
                      ) : route.path === "/auditoria" ? (
                        <AuditPage />
                      ) : route.path === "/fuentes-de-datos" ? (
                        <DatasourcesPage />
                      ) : route.path === "/proveedores-ia" ? (
                        <ProvidersPage />
                      ) : route.path === "/usuarios" ? (
                        <UsersPage />
                      ) : (
                        <EmptyState route={route} />
                      )
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
