import { Navigate, Route, Routes } from 'react-router-dom';

import { useAuth } from './auth/AuthContext';
import { Layout } from './components/Layout';
import { LoadingCat } from './components/ui';
import { AccountsPage } from './pages/AccountsPage';
import { ActivityPage } from './pages/ActivityPage';
import { AuditPage } from './pages/AuditPage';
import { CredentialsPage } from './pages/CredentialsPage';
import { ErrorsPage } from './pages/ErrorsPage';
import { FeedbackPage } from './pages/FeedbackPage';
import { KeywordsPage } from './pages/KeywordsPage';
import { LoginPage } from './pages/LoginPage';
import { OverviewPage } from './pages/OverviewPage';
import { ProjectDashboardPage } from './pages/ProjectDashboardPage';
import { ProjectSettingsPage } from './pages/ProjectSettingsPage';
import { ProjectsPage } from './pages/ProjectsPage';
import { RulesPage } from './pages/RulesPage';
import { SignalsPage } from './pages/SignalsPage';
import { SnapshotsPage } from './pages/SnapshotsPage';
import { TeamPage } from './pages/TeamPage';

export function App() {
  const { user } = useAuth();

  if (user === undefined) return <LoadingCat />;
  if (user === null) return <LoginPage />;

  // Разделы администратора: специалист перенаправляется на сводку.
  const admin = (page: JSX.Element) => (user.role === 'admin' ? page : <Navigate to="/" replace />);

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/signals" element={<SignalsPage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/projects/:projectRef" element={<ProjectDashboardPage />} />
        <Route path="/projects/:projectRef/settings" element={<ProjectSettingsPage />} />
        <Route path="/projects/:projectRef/keywords/:integrationId" element={<KeywordsPage />} />
        <Route path="/projects/:projectRef/:kind/:integrationId" element={<SnapshotsPage />} />
        <Route path="/credentials" element={admin(<CredentialsPage />)} />
        <Route path="/rules" element={admin(<RulesPage />)} />
        <Route path="/errors" element={admin(<ErrorsPage />)} />
        <Route path="/audit" element={admin(<AuditPage />)} />
        <Route path="/activity" element={admin(<ActivityPage />)} />
        <Route path="/feedback" element={admin(<FeedbackPage />)} />
        <Route path="/team" element={admin(<TeamPage />)} />
        <Route path="/accounts" element={admin(<AccountsPage />)} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
