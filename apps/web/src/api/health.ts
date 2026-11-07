import { useQuery } from "@tanstack/react-query";
import { getHealth } from "./generated";

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: async () => {
      const { data, error } = await getHealth();
      if (error || !data) throw new Error("health check failed");
      return data;
    },
  });
}
