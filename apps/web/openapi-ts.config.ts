import { defineConfig } from "@hey-api/openapi-ts";

// Regenerate with `mise run gen:api` after changing FastAPI routes or models.
export default defineConfig({
  input: "./openapi.json",
  output: "./src/api/generated",
  plugins: ["@hey-api/client-fetch", "@hey-api/typescript", "@hey-api/sdk"],
});
