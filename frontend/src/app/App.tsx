import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Navigate, Route, Routes } from "react-router-dom";
import { TooltipProvider } from "@/components/ui/tooltip";
import { EmptyState } from "./EmptyState";
import { Layout } from "./Layout";
import { appRoutes } from "./routes";

const queryClient = new QueryClient();

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Navigate to={appRoutes[0].path} replace />} />
            {appRoutes.map((route) => (
              <Route key={route.path} path={route.path} element={<EmptyState route={route} />} />
            ))}
            <Route path="*" element={<Navigate to={appRoutes[0].path} replace />} />
          </Route>
        </Routes>
      </TooltipProvider>
    </QueryClientProvider>
  );
}
