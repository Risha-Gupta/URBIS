import { api } from './axios';

export type Building = {
  building_id: string | number;
  dataset_id?: string | number;
  half?: string;
  coverage_class?: string;
  num_points?: number;
  footprint_area_m2?: number;
  lon?: number;
  lat?: number;
  status?: string;
  action?: string;
  model_confidence?: number;
  combined_confidence?: number;
  confidence_class?: string;
  decision_policy?: string;
  total_roof_area_m2?: number;
  usable_roof_area_m2?: number;
  annual_kwh?: number;
  annual_kwh_unshaded?: number;
  solar_reliability?: string;
  p_bad?: number;
  review_rank?: number;
  solar_review?: boolean;
  has_model?: boolean;
  [key: string]: unknown;
};

export type Job = {
  job_id: string;
  building_id?: string | number | null;
  status: string;
  review_status?: string;
  progress?: number;
  created_at?: string;
  updated_at?: string;
  input_path?: string;
  final_version_id?: string | null;
  versions?: JobVersion[];
  comments?: ReviewComment[];
  [key: string]: unknown;
};

export type JobVersion = {
  version_no: number;
  status?: string;
  params?: Record<string, unknown>;
  stage_reached?: string;
  confidence?: number;
  action?: string;
  n_corners?: number;
  n_edges?: number;
  mesh_path?: string;
  error?: string;
  decision?: string;
  created_at?: string;
};

export type ReviewComment = { id?: number; author?: string; body: string; version_no?: number; created_at?: string };

function listFrom<T>(data: unknown, keys: string[] = []): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>;
    for (const key of keys) if (Array.isArray(obj[key])) return obj[key] as T[];
    if (Array.isArray(obj.items)) return obj.items as T[];
    if (Array.isArray(obj.results)) return obj.results as T[];
  }
  return [];
}

export async function getBuildings(params: Record<string, string | number | boolean | undefined> = {}) {
  const { data } = await api.get('/buildings', { params });
  return listFrom<Building>(data, ['buildings', 'items', 'results']);
}
export async function getBuilding(id: string) { return (await api.get(`/buildings/${encodeURIComponent(id)}`)).data; }
export async function getBuildingPlanes(id: string) { return listFrom<Record<string, unknown>>((await api.get(`/buildings/${encodeURIComponent(id)}/planes`)).data, ['planes']); }
export async function getBuildingModelUrl(id: string) { return `${api.defaults.baseURL}/buildings/${encodeURIComponent(id)}/model`; }
export async function getRoofs(params: Record<string, string | number | undefined> = {}) {
  const { data } = await api.get('/roofs', { params });
  return listFrom<Building>(data, ['roofs', 'buildings', 'items']);
}
export async function getJobsList(status?: string) {
  const { data } = await api.get('/jobs', { params: status ? { status } : undefined });
  return listFrom<Job>(data, ['jobs', 'items', 'results']);
}
export async function getJob(id: string) { return (await api.get(`/jobs/${encodeURIComponent(id)}`)).data as Job; }
export async function createJob(file: File, buildingId?: string) {
  const body = new FormData(); body.append('file', file); if (buildingId) body.append('building_id', buildingId);
  return (await api.post('/jobs', body, { headers: { 'Content-Type': 'multipart/form-data' } })).data;
}
export async function retryJob(id: string, params: { score_thr?: number; passes?: number; seed?: number } = {}) { return (await api.post(`/jobs/${encodeURIComponent(id)}/retry`, params)).data; }
export async function reviewJob(id: string, decision: 'approve' | 'reject', payload: { version_no: number; reviewer: string; note?: string }) { return (await api.post(`/jobs/${encodeURIComponent(id)}/${decision}`, payload)).data; }
export async function addJobComment(id: string, payload: { version_no: number; author: string; body: string }) { return (await api.post(`/jobs/${encodeURIComponent(id)}/comments`, payload)).data; }
export function jobEventsUrl(id: string) { return `${api.defaults.baseURL}/jobs/${encodeURIComponent(id)}/events`; }
