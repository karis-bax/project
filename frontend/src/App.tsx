import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import { Shell } from './components/Shell'
import { EmptyState } from './components/ui'
import { currentMonth } from './lib/month'
import { BudgetPage } from './routes/BudgetPage'
import { ImportPage } from './routes/ImportPage'
import { InsightsPage } from './routes/InsightsPage'
import { RulesPage } from './routes/RulesPage'
import { SettingsPage } from './routes/SettingsPage'
import { TransactionsPage } from './routes/TransactionsPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route
            index
            element={<Navigate to={`/budget/${currentMonth()}`} replace />}
          />
          <Route path="budget/:month" element={<BudgetPage />} />
          <Route path="transactions" element={<TransactionsPage />} />
          <Route path="insights" element={<InsightsPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="settings/import" element={<ImportPage />} />
          <Route path="settings/rules" element={<RulesPage />} />
          <Route
            path="*"
            element={
              <EmptyState
                title="Page not found"
                hint="The page you are looking for does not exist."
              />
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
