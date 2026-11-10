import { api } from './axios';

export interface StatsSummary {
  scope?: string;
  n_buildings?: number;
  by_action?: Record<string, number>;
  by_status?: Record<string, number>;
  by_solar_reliability?: Record<string, number>;
  by_coverage_class?: Record<string, number>;
  escalate_rate?: number;
  total_gwh_shaded?: number;
  total_gwh_unshaded?: number;
  gwh_by_action?: Record<string, number>;
  yield_at_risk?: number;
  caveats?: string[];
}

export interface DatasetSummary {
  dataset_id?: string | number;
  name?: string;
  description?: string;
  [key: string]: unknown;
}

export interface JobSummary {
  job_id: string;
  building_id?: string | number;
  status: string;
  progress?: number;
  review_status?: string;
  created_at?: string;
  updated_at?: string;
}

export async function getStatsSummary(): Promise<StatsSummary> {
  const response = await api.get<StatsSummary>('/stats/summary');
  return response.data;
}

export async function getDatasets(): Promise<DatasetSummary[]> {
  const response = await api.get<DatasetSummary[]>('/datasets');
  return Array.isArray(response.data) ? response.data : [];
}

export async function getJobs(): Promise<JobSummary[]> {
  const response = await api.get<JobSummary[]>('/jobs');
  return Array.isArray(response.data) ? response.data : [];
}
