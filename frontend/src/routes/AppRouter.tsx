import { Navigate, Route, Routes } from 'react-router-dom';
import App from '../App';
import Dashboard from '../pages/Dashboard';
import Buildings from '../pages/Buildings';
import BuildingDetail from '../pages/BuildingDetail';
import Jobs from '../pages/Jobs';
import JobDetail from '../pages/JobDetail';
import Reviews from '../pages/Reviews';
import Analytics from '../pages/Analytics';
import Explorer from '../pages/Explorer';
function PlaceholderPage({ title, eyebrow }: { title: string; eyebrow: string }) { return <div className="page-placeholder"><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>This workspace is ready for the connected URBIS data flow.</p></div>; }
export default function AppRouter() { return <Routes><Route element={<App />}><Route index element={<Navigate to="/dashboard" replace />} /><Route path="dashboard" element={<Dashboard />} /><Route path="explorer" element={<Explorer />} /><Route path="buildings" element={<Buildings />} /><Route path="buildings/:id" element={<BuildingDetail />} /><Route path="jobs" element={<Jobs />} /><Route path="jobs/:id" element={<JobDetail />} /><Route path="reviews" element={<Reviews />} /><Route path="analytics" element={<Analytics />} /><Route path="settings" element={<PlaceholderPage eyebrow="Workspace controls" title="Settings" />} /></Route></Routes>; }
