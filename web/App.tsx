import React from 'react'
import { HashRouter as Router, Routes, Route } from 'react-router-dom'
import { Toaster } from 'sonner'
import { Layout } from '@/components/Layout'
import { Dashboard } from '@/pages/Dashboard'
import { NovelDetail } from '@/pages/NovelDetail'
import { WorkflowLayout } from '@/pages/workflow/WorkflowLayout'
import { VideosPage } from '@/pages/Videos'
import { ConfigPage } from '@/pages/Config'

const App: React.FC = () => {
  return (
    <>
      <Toaster
        richColors
        position="top-right"
        toastOptions={{
          className: 'border border-border',
          style: { background: 'hsl(217.2 32.6% 17.5%)', color: 'hsl(210 40% 98%)' },
        }}
      />
      <Router>
        <Layout>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/novel/:id" element={<NovelDetail />} />
            <Route path="/novel/:novelId/chapter/:chapterId/step/:stepId" element={<WorkflowLayout />} />
            <Route path="/videos" element={<VideosPage />} />
            <Route path="/config" element={<ConfigPage />} />
          </Routes>
        </Layout>
      </Router>
    </>
  )
}

export default App
