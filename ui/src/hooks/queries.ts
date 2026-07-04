// react-query hooks over the api client.
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  BatchRequest,
  JobStatus,
  ReadyResponse,
  RegisterVideoRequest,
  SearchMode,
  VideoFilters,
} from "@/lib/types";

export function useHealth() {
  return useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 15_000,
  });
}

export function useReady(): UseQueryResult<ReadyResponse> {
  return useQuery({
    queryKey: ["ready"],
    queryFn: api.ready,
    refetchInterval: 8_000,
  });
}

export function useVideos(page: number, pageSize: number, filters: VideoFilters) {
  return useQuery({
    queryKey: ["videos", page, pageSize, filters],
    queryFn: () => api.listVideos(page, pageSize, filters),
    placeholderData: (prev) => prev,
  });
}

export function useVideo(id: string | undefined) {
  return useQuery({
    queryKey: ["video", id],
    queryFn: () => api.getVideo(id!),
    enabled: !!id,
  });
}

// Poll a job until it reaches a terminal state.
export function useJob(id: string | undefined) {
  return useQuery({
    queryKey: ["job", id],
    queryFn: () => api.getJob(id!),
    enabled: !!id,
    refetchInterval: (query) => {
      const s = (query.state.data as JobStatus | undefined)?.state;
      return s === "done" || s === "failed" ? false : 2000;
    },
  });
}

export function useSearch(q: string, mode: SearchMode, limit: number, enabled: boolean) {
  return useQuery({
    queryKey: ["search", q, mode, limit],
    queryFn: () => api.search(q, mode, limit),
    enabled: enabled && q.trim().length > 0,
  });
}

export function useRegisterVideo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: RegisterVideoRequest) => api.registerVideo(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["videos"] }),
  });
}

export function useUploadVideo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, force }: { file: File; force: boolean }) =>
      api.uploadVideo(file, force),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["videos"] }),
  });
}

export function useBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: BatchRequest) => api.batch(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["videos"] }),
  });
}

export function useSoftDelete() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.softDelete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["videos"] }),
  });
}
