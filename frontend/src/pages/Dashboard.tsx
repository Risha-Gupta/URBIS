import { useEffect, useMemo, useState } from 'react';
import { Activity, ArrowUpRight, Building2, ChevronRight, CircleAlert, Cloud, Database, Layers3, RefreshCw, Server, Sun, Waypoints } from 'lucide-react';
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts';
import { getDatasets, getJobs, getStatsSummary, type JobSummary, type StatsSummary } from '../services/api/analyticsApi';

const statusColors: Record<string, string> = {
  completed: '#42d6a4',
  approved: '#42d6a4',
  pending: '#f0b35b',
  processing: '#58a6ff',
  failed: '#f16b6b',
  queued: '#8290a8',
};

const fallbackStatus = [
  { name: 'Completed', value: 0, color: '#42d6a4' },
  { name: 'Processing', value: 0, color: '#58a6ff' },
  { name: 'Pending review', value: 0, color: '#f0b35b' },
  { name: 'Failed', value: 0, color: '#f16b6b' },
];

function formatNumber(value: number | undefined) {
  return typeof value === 'number' ? new Intl.NumberFormat('en-US').format(value) : '—';
}

function formatDate(value?: string) {
  if (!value) return 'Awaiting data';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function getStatusData(stats: StatsSummary | null) {
  if (!stats?.by_status) return fallbackStatus;
  return Object.entries(stats.by_status).map(([name, value]) => ({
    name: name.split('_').join(' ').replace(/\b\w/g, (letter: string) => letter.toUpperCase()),
    value,
    color: statusColors[name.toLowerCase()] || '#8290a8',
  }));
}

export default function Dashboard() {
  const [stats, setStats] = useState<StatsSummary | null>(null);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [datasetCount, setDatasetCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  async function loadDashboard() {
    setLoading(true);
    const [statsResult, jobsResult, datasetsResult] = await Promise.allSettled([getStatsSummary(), getJobs(), getDatasets()]);
    const statsOk = statsResult.status === 'fulfilled';
    if (statsOk) setStats(statsResult.value);
    if (jobsResult.status === 'fulfilled') setJobs(jobsResult.value);
    if (datasetsResult.status === 'fulfilled') setDatasetCount(datasetsResult.value.length);
    setConnected(statsOk || jobsResult.status === 'fulfilled');
    setLastUpdated(new Date());
    setLoading(false);
  }

  useEffect(() => {
    void loadDashboard();
  }, []);

  const statusData = useMemo(() => getStatusData(stats), [stats]);
  const totalStatuses = statusData.reduce((total, item) => total + item.value, 0);
  const reviewCount = stats?.by_action?.review ?? stats?.by_status?.pending ?? 0;
  const confidenceRate = stats?.escalate_rate !== undefined ? `${Math.max(0, 100 - stats.escalate_rate * 100).toFixed(1)}%` : '—';

  return (
    <main className="dashboard-page">
      <div className="page-heading">
        <div>
          <div className="eyebrow-row"><span className="eyebrow">Operations overview</span><span className="live-dot" /> Live workspace</div>
          <h1>Good morning, operator.</h1>
          <p>Monitor reconstruction quality, urban coverage, and solar potential across your digital twin.</p>
        </div>
        <button className="ghost-button" onClick={() => void loadDashboard()} disabled={loading}><RefreshCw size={15} className={loading ? 'spin' : ''} /> Refresh data</button>
      </div>

      {!connected && <div className="connection-banner"><CircleAlert size={17} /><div><strong>Backend connection unavailable</strong><span>Connect the FastAPI service to populate this workspace with live data.</span></div><button onClick={() => void loadDashboard()}>Try again <ArrowUpRight size={14} /></button></div>}

      <section className="metric-grid">
        <MetricCard icon={<Building2 size={18} />} label="Buildings in catalog" value={formatNumber(stats?.n_buildings)} detail={stats?.scope || 'Phase 7 source of truth'} tone="teal" loading={loading} />
        <MetricCard icon={<Waypoints size={18} />} label="Reconstruction confidence" value={confidenceRate} detail="Derived from policy escalation" tone="blue" loading={loading} />
        <MetricCard
          icon={<Sun size={18} />}
          label="Yield at risk"
          value={
            typeof stats?.yield_at_risk?.share_in_accepted_bad_rule === "number"
              ? `${(stats.yield_at_risk.share_in_accepted_bad_rule * 100).toFixed(1)}%`
              : "—"
          }
          detail="Estimated generation risk in accepted buildings"
          tone="amber"
          loading={loading}
        />
        <MetricCard icon={<Layers3 size={18} />} label="Awaiting review" value={formatNumber(reviewCount)} detail="Decision queue" tone="rose" loading={loading} />
      </section>

      <section className="dashboard-grid">
        <article className="panel status-panel">
          <PanelHeader eyebrow="Coverage health" title="Reconstruction status" action="View buildings" />
          <div className="chart-row">
            <div className="donut-wrap">
              <ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={statusData} dataKey="value" nameKey="name" innerRadius={61} outerRadius={83} paddingAngle={3} stroke="none">{statusData.map((entry) => <Cell key={entry.name} fill={entry.color} />)}</Pie><Tooltip contentStyle={{ background: '#18212d', border: '1px solid #2b3949', borderRadius: 8, color: '#f1f5f9' }} /></PieChart></ResponsiveContainer>
              <div className="donut-label"><strong>{formatNumber(totalStatuses)}</strong><span>Total records</span></div>
            </div>
            <div className="legend-list">{statusData.map((entry) => <div className="legend-item" key={entry.name}><span className="legend-swatch" style={{ background: entry.color }} /><span>{entry.name}</span><strong>{formatNumber(entry.value)}</strong></div>)}</div>
          </div>
          <div className="panel-footnote"><Database size={14} /> Status values are returned by the Phase 7 building service.</div>
        </article>

        <article className="panel solar-panel">
          <PanelHeader eyebrow="Energy intelligence" title="Solar potential" action="Open analytics" />
          <div className="solar-total"><span>Annual generation, unshaded</span><strong>{stats?.total_gwh_unshaded !== undefined ? `${stats.total_gwh_unshaded.toFixed(2)} GWh` : '—'}</strong></div>
          <div className="solar-bars">{Object.entries(stats?.gwh_by_action || {}).slice(0, 4).map(([label, value], index) => <div className="bar-row" key={label}><div className="bar-label"><span>{label.split('_').join(' ')}</span><strong>{typeof value === 'number' ? `${value.toFixed(2)} GWh` : '—'}</strong></div><div className="bar-track"><span style={{ width: `${Math.min(100, 20 + index * 19)}%`, background: ['#42d6a4', '#58a6ff', '#f0b35b', '#f16b6b'][index] }} /></div></div>)}{!stats?.gwh_by_action && <div className="empty-inline"><Sun size={16} /> Solar breakdown will appear when the backend responds.</div>}</div>
          <div className="solar-risk"><span className="risk-icon"><Activity size={15} /></span><div><strong>{stats?.total_gwh_shaded !== undefined ? `${stats.total_gwh_shaded.toFixed(2)} GWh` : '—'}</strong><span>Shaded generation estimate</span></div><ChevronRight size={16} /></div>
        </article>
      </section>

      <section className="lower-grid">
        <article className="panel jobs-panel"><PanelHeader eyebrow="Phase 8 workflow" title="Recent processing jobs" action="Open job queue" /><div className="job-table"><div className="table-head"><span>Job</span><span>Building</span><span>Status</span><span>Updated</span></div>{jobs.slice(0, 5).map((job) => <div className="table-row" key={job.job_id}><span className="job-id">{job.job_id}</span><span>{job.building_id ?? 'Unassigned'}</span><StatusPill status={job.status} /><span className="muted">{formatDate(job.updated_at || job.created_at)}</span></div>)}{jobs.length === 0 && <EmptyState icon={<Server size={17} />} text={connected ? 'No processing jobs returned yet.' : 'Job activity will appear after connection.'} />}</div></article>
        <article className="panel signal-panel"><PanelHeader eyebrow="Workspace signal" title="System readiness" /><div className="signal-list"><Signal icon={<Server size={16} />} label="FastAPI data service" value={connected ? 'Connected' : 'Offline'} tone={connected ? 'good' : 'bad'} /><Signal icon={<Database size={16} />} label="Datasets available" value={datasetCount !== null ? formatNumber(datasetCount) : '—'} tone="neutral" /><Signal icon={<Cloud size={16} />} label="GLB asset collection" value="Not configured" tone="warning" /></div><div className="asset-note">GLB assets stay separate from backend reconstruction records. Configure the asset manifest to enable 3D model availability.</div></article>
      </section>
      <div className="updated-line">{lastUpdated ? `Last checked ${lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Checking workspace'} <span>•</span> Data source: URBIS API</div>
    </main>
  );
}

function MetricCard({ icon, label, value, detail, tone, loading }: { icon: React.ReactNode; label: string; value: string; detail: string; tone: string; loading: boolean }) {
  return <div className={`metric-card ${tone}`}><div className="metric-top"><span className="metric-icon">{icon}</span><span className="metric-label">{label}</span><span className="metric-menu">•••</span></div><div className={`metric-value ${loading ? 'skeleton-text' : ''}`}>{value}</div><div className="metric-detail">{detail}</div></div>;
}

function PanelHeader({ eyebrow, title, action }: { eyebrow: string; title: string; action?: string }) {
  return <div className="panel-header"><div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2></div>{action && <button className="text-button">{action}<ArrowUpRight size={14} /></button>}</div>;
}

function StatusPill({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  return <span className={`status-pill ${normalized}`}><span />{status.split('_').join(' ')}</span>;
}

function Signal({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: string; tone: string }) {
  return <div className="signal-row"><span className={`signal-icon ${tone}`}>{icon}</span><span>{label}</span><strong className={tone}>{value}</strong></div>;
}

function EmptyState({ icon, text }: { icon: React.ReactNode; text: string }) {
  return <div className="empty-state">{icon}<span>{text}</span></div>;
}
