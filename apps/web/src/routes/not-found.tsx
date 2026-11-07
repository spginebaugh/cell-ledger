import { Link } from "@tanstack/react-router";
import { Page, TopBar } from "@/components/layout/top-bar";

export function NotFound() {
  return (
    <>
      <TopBar />
      <Page width="narrow">
        <h1>There is nothing here</h1>
        <p className="mt-3 text-ink-2">
          Check the link, or{" "}
          <Link to="/" className="underline">
            start from a question
          </Link>
          .
        </p>
      </Page>
    </>
  );
}
