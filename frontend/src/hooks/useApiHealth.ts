import { useQuery } from "@tanstack/react-query";
import axios from "axios";

export function useApiHealth() {
  return useQuery({
    queryKey: ["api-health"],
    queryFn: async () => {
      const { data } = await axios.get<{ status: string; env: string }>("/api/health");
      return data;
    },
    refetchInterval: 30_000,
    retry: 1,
  });
}
