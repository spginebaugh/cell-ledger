import { useHealth } from "./api/health";

export function App() {
  const health = useHealth();

  return (
    <main>
      <h1>cell-ledger</h1>
      <p>Find, triage and analyze public RNA-seq data from GEO.</p>
      <p data-testid="api-status">
        {health.isPending && "Checking API…"}
        {health.isError && `API unreachable: ${health.error.message}`}
        {health.isSuccess &&
          `API ${health.data.status} (api ${health.data.api_version}, core ${health.data.core_version})`}
      </p>
    </main>
  );
}
