import { LogOut, Menu } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/AuthProvider";
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { appRoutes } from "./routes";

function Logo() {
  return (
    <picture>
      <source srcSet="/logo-dark.svg" media="(prefers-color-scheme: dark)" />
      <img src="/logo-light.svg" alt="ChatIApp" className="h-8 w-auto" />
    </picture>
  );
}

function Nav() {
  const { user } = useAuth();
  const visibleRoutes = appRoutes.filter((route) => !route.adminOnly || user?.is_admin);
  return (
    <nav aria-label="Principal" className="flex flex-col gap-1">
      {visibleRoutes.map(({ path, title, icon: Icon }) => (
        <NavLink
          key={path}
          to={path}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
              isActive
                ? "bg-accent text-accent-foreground"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )
          }
        >
          <Icon className="size-4" aria-hidden />
          {title}
        </NavLink>
      ))}
    </nav>
  );
}

function SessionFooter() {
  const { user, logout } = useAuth();
  return (
    <div className="mt-auto flex flex-col gap-2 border-t pt-4">
      <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
      <Button variant="ghost" size="sm" className="justify-start" onClick={() => void logout()}>
        <LogOut aria-hidden /> Cerrar sesión
      </Button>
    </div>
  );
}

export function Layout() {
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-64 shrink-0 flex-col gap-6 border-r bg-card p-4 md:flex">
        <Logo />
        <Nav />
        <SessionFooter />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 h-16 border-b bg-card px-4 md:hidden">
          <Sheet>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Abrir menú">
                <Menu />
              </Button>
            </SheetTrigger>
            <SheetContent side="left">
              <SheetTitle className="sr-only">Menú</SheetTitle>
              <SheetDescription className="sr-only">Navegación principal</SheetDescription>
              <Logo />
              <Nav />
            </SheetContent>
          </Sheet>
          <Logo />
        </header>
        <main className="flex-1 p-4 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
