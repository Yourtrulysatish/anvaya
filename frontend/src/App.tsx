import { HashRouter, Route, Routes } from 'react-router-dom'
import { Shell } from './components/Shell'
import { HomePage } from './pages/Home'
import { UniversePage } from './pages/Universe'

export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<HomePage />} />
          <Route path="universe" element={<UniversePage />} />
          <Route path="*" element={<div className="p-10 text-silver-500">Coming online in this build.</div>} />
        </Route>
      </Routes>
    </HashRouter>
  )
}
