import { createRootRoute, createRoute, createRouter, Outlet } from "@tanstack/react-router";
import { ComparePage } from "./routes/compare";
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
});
export const compareRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/s/$sessionId/compare/$name",
  component: ComparePage,
});

const routeTree = rootRoute.addChildren([homeRoute, sessionRoute, runRoute, compareRoute]);

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
