import { useGrip } from '@owebeeone/grip-react';
import { CURRENT_VIEW, CURRENT_VIEW_TAP, THEME } from './grips';
import type { ViewId } from './types';
import OnboardingView from './components/OnboardingView';
import WorkspaceStatusView from './components/WorkspaceStatusView';
import FileViewerView from './components/FileViewerView';
import DiffViewerView from './components/DiffViewerView';
import SessionsView from './components/SessionsView';
import SettingsView from './components/SettingsView';
import ChatPanel from './components/ChatPanel';
import { Icon } from './components/icons';
import './lab.css';

// Chat is a persistent right-hand panel (see ChatPanel), not a nav view.
const TABS: { id: ViewId; label: string; icon: string }[] = [
  { id: 'status', label: 'Workspace', icon: 'workspace' },
  { id: 'file', label: 'Files', icon: 'files' },
  { id: 'diff', label: 'Diff', icon: 'diff' },
  { id: 'sessions', label: 'Sessions', icon: 'terminal' },
  { id: 'onboarding', label: 'Collaborators', icon: 'collaborators' },
  { id: 'settings', label: 'Settings', icon: 'settings' },
];

export default function LabApp() {
  const view = useGrip(CURRENT_VIEW);
  const viewTap = useGrip(CURRENT_VIEW_TAP);
  const theme = useGrip(THEME) ?? 'dark';

  return (
    <div className="lab-root" data-theme={theme}>
      <header className="lab-tabbar">
        <div className="lab-brand">grip-lab</div>
        <nav className="lab-tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`lab-tab${view === t.id ? ' active' : ''}`}
              onClick={() => viewTap?.set(t.id)}
              title={t.label}
            >
              <Icon name={t.icon} />
              <span>{t.label}</span>
            </button>
          ))}
        </nav>
      </header>
      <div className="lab-body">
        <main className="lab-main">
          {view === 'status' && <WorkspaceStatusView />}
          {view === 'file' && <FileViewerView />}
          {view === 'diff' && <DiffViewerView />}
          {view === 'sessions' && <SessionsView />}
          {view === 'onboarding' && <OnboardingView />}
          {view === 'settings' && <SettingsView />}
        </main>
        <ChatPanel />
      </div>
    </div>
  );
}
