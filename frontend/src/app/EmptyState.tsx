import type { AppRoute } from "./routes";

export function EmptyState({ route }: { route: AppRoute }) {
  const Icon = route.icon;
  return (
    <section className="mx-auto flex max-w-xl flex-col items-center gap-4 py-24 text-center">
      <div className="flex size-12 items-center justify-center rounded-xl bg-accent text-accent-foreground">
        <Icon className="size-6" aria-hidden />
      </div>
      <h1 className="text-2xl font-semibold tracking-tight">{route.title}</h1>
      <p className="text-muted-foreground">{route.description}</p>
      <p className="text-sm text-muted-foreground">Todavía no hay nada por mostrar.</p>
    </section>
  );
}
