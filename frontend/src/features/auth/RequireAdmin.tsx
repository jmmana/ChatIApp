import type { ReactNode } from "react";
import { useAuth } from "./AuthProvider";

/** Oculta la pantalla a quien no es administrador; el servidor impone el permiso de verdad. */
export function RequireAdmin({
  required,
  children,
}: {
  required: boolean;
  children: ReactNode;
}) {
  const { user } = useAuth();
  if (!required || user?.is_admin) return <>{children}</>;
  return (
    <section role="alert" className="mx-auto max-w-md py-12 text-center">
      <h1 className="text-xl font-semibold tracking-tight">Necesitas permisos de administrador</h1>
      <p className="mt-2 text-sm text-muted-foreground">
        Esta pantalla es solo para administradores. Pide acceso a quien administra ChatIApp.
      </p>
    </section>
  );
}
