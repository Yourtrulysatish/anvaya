import { HashRouter, Route, Routes } from 'react-router-dom'
import { Shell } from './components/Shell'
import { HomePage } from './pages/Home'
import { UniversePage } from './pages/Universe'
import { GraphPage } from './pages/Graph'
import { LabPage } from './pages/Lab'
import { ReportsPage } from './pages/Reports'
import { SettingsPage } from './pages/Settings'
import { ProjectsPage } from './pages/Projects'
import { NewAnalysisPage } from './pages/NewAnalysis'
import { ProjectPage } from './pages/Project'

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<HomePage />} />
          <Route path="universe" element={<UniversePage />} />
          <Route path="vegeta" element={<UniversePage initial="vegeta" />} />
          <Route path="graph" element={<GraphPage />} />
          <Route path="lab" element={<LabPage />} />
          <Route path="reports" element={<ReportsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="projects" element={<ProjectsPage />} />
          <Route path="new" element={<NewAnalysisPage />} />
          <Route path="projects/:id" element={<ProjectPage />} />
          <Route path="projects/:id/:tab" element={<ProjectPage />} />
          <Route path="*" element={<div className="p-10 text-silver-500">Page not found.</div>} />
        </Route>
      </Routes>
    </HashRouter>
  )
}
