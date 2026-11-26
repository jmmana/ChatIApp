import type { ReactNode } from "react";
import { useAuth } from "./AuthProvider";

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  if (user?.is_admin) return children;

  return (
    <section role="alert" className="mx-auto max-w-xl py-12 text-center">
      <h1 className="text-xl font-semibold">Necesitas permisos de administrador</h1>
    </section>
  );
}
