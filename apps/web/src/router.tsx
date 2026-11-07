import { createRootRoute, createRoute, createRouter, Outlet } from "@tanstack/react-router";
import { ComparePage } from "./routes/compare";
import { EvalsPage } from "./routes/evals";
import { GenePage } from "./routes/gene";
import { HomePage } from "./routes/home";
import { NotFound } from "./routes/not-found";
import { RunPage } from "./routes/run";
import { SessionPage } from "./routes/session";

const rootRoute = createRootRoute({ component: () => <Outlet />, notFoundComponent: NotFound });

export const homeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: HomePage,
});
export const sessionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/s/$sessionId",
  component: SessionPage,
});
export const runRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/s/$sessionId/runs/$gse/$contrast",
  component: RunPage,
  // ?gene=SYMBOL opens that gene's panel, so a gene can be linked to.
  validateSearch: (search: Record<string, unknown>): { gene?: string } =>
    typeof search.gene === "string" && search.gene.trim() ? { gene: search.gene.trim() } : {},
});
export const compareRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/s/$sessionId/compare/$name",
  component: ComparePage,
});

export const geneRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/gene/$symbol",
  component: GenePage,
});

export const evalsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/evals",
  component: EvalsPage,
});

const routeTree = rootRoute.addChildren([
  homeRoute,
  sessionRoute,
  runRoute,
  compareRoute,
  geneRoute,
  evalsRoute,
]);

export const router = createRouter({
  routeTree,
  defaultPreload: "intent",
  scrollRestoration: true,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
