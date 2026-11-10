import { useState } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { Activity, BarChart3, Bell, Building2, ChevronDown, CircleHelp, Command, Database, FileCheck2, FolderKanban, LayoutDashboard, Menu, PanelLeftClose, PanelLeftOpen, Search, Settings, ShieldCheck, Waypoints, X } from 'lucide-react';
import Dashboard from './pages/Dashboard';
import './App.css';

const navigation = [
  { label: 'Dashboard', to: '/dashboard', icon: LayoutDashboard },
  { label: 'City Explorer', to: '/explorer', icon: Waypoints, accent: true },
  { label: 'Buildings', to: '/buildings', icon: Building2 },
  { label: 'Processing Jobs', to: '/jobs', icon: FolderKanban },
  { label: 'Review Workspace', to: '/reviews', icon: FileCheck2, badge: '4' },
  { label: 'Analytics', to: '/analytics', icon: BarChart3 },
];

export default function App() {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();
  const isDashboard = location.pathname === '/dashboard' || location.pathname === '/';

  return (
    <div className="app-shell">
      <aside className={`sidebar ${sidebarOpen ? '' : 'collapsed'} ${mobileOpen ? 'mobile-open' : ''}`}>
        <div className="brand"><span className="brand-mark"><Command size={17} strokeWidth={2.7} /></span>{sidebarOpen && <span className="brand-name">URBIS<span>.</span></span>}<button className="mobile-close" onClick={() => setMobileOpen(false)}><X size={17} /></button></div>
        <div className="workspace-switcher"><span className="workspace-avatar">U</span>{sidebarOpen && <><span className="workspace-name">Urban systems lab</span><ChevronDown size={15} /></>}</div>
        <nav className="main-nav"><span className="nav-label">Workspace</span>{navigation.map(({ label, to, icon: Icon, badge, accent }) => <NavLink key={to} to={to} className={({ isActive }) => `nav-item ${isActive ? 'active' : ''} ${accent ? 'with-accent' : ''}`} onClick={() => setMobileOpen(false)}><Icon size={18} /><span>{sidebarOpen && label}</span>{sidebarOpen && badge && <b>{badge}</b>}</NavLink>)}</nav>
        <div className="sidebar-bottom"><NavLink to="/settings" className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}><Settings size={18} />{sidebarOpen && <span>Settings</span>}</NavLink><button className="nav-item help-item"><CircleHelp size={18} />{sidebarOpen && <span>Help center</span>}</button><div className="user-block"><span className="user-avatar">OS</span>{sidebarOpen && <div><strong>Operations</strong><span>Admin workspace</span></div>}</div></div>
      </aside>
      <div className="main-column">
        <header className="topbar"><button className="mobile-menu" onClick={() => setMobileOpen(true)}><Menu size={20} /></button><button className="collapse-button" onClick={() => setSidebarOpen((open) => !open)}>{sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}</button><div className="breadcrumb"><span>URBIS</span><span>/</span><strong>{isDashboard ? 'Dashboard' : location.pathname.slice(1).replace('-', ' ')}</strong></div><div className="topbar-actions"><div className="global-search"><Search size={16} /><input placeholder="Search building ID..." /><kbd>⌘ K</kbd></div><button className="icon-button"><Bell size={18} /><i /></button><Link to="/settings" className="top-avatar">OS</Link></div></header>
        <div className="content-wrap">{isDashboard ? <Dashboard /> : <Outlet />}</div>
      </div>
    </div>
  );
}
