import Navbar from "@/components/Navbar";
import BackendStatus from "@/components/BackendStatus";

export default function Home() {
  return (
    <div className="min-h-screen flex flex-col justify-between">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:px-4 focus:py-2 focus:bg-white focus:text-slate-900 focus:outline-none focus:ring-2 focus:ring-blue-600 dark:focus:bg-slate-900 dark:focus:text-white rounded shadow-md"
      >
        Skip to content
      </a>

      <Navbar />

      <main id="main-content" className="flex-1 max-w-5xl w-full mx-auto px-4 sm:px-6 py-12 sm:py-16">
        <div className="space-y-8 max-w-2xl">
          <div className="space-y-3">
            <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-slate-900 dark:text-slate-50">
              AI Travel Concierge
            </h1>
            <p className="text-lg text-slate-600 dark:text-slate-400">
              An AI-powered travel research and planning web application.
            </p>
          </div>

          <div className="p-4 sm:p-5 rounded-lg border border-amber-200 bg-amber-50/70 dark:border-amber-900/50 dark:bg-amber-950/30 text-amber-900 dark:text-amber-200">
            <p className="text-sm font-medium">
              Phase 1 (foundation) in progress; no AI planning features are implemented yet.
            </p>
          </div>

          <div className="space-y-4 text-slate-700 dark:text-slate-300 leading-relaxed">
            <p>
              AI Travel Concierge assists travelers in discovering destinations, researching points of
              interest, and organizing travel itineraries. This platform is strictly a travel discovery
              and planning assistant, <strong>not a booking engine</strong>. No reservation, payment,
              ticketing, or purchasing features are provided.
            </p>
            <p>
              Full planning capabilities, LLM integrations, and external travel data providers will be
              introduced in subsequent phases once project scaffolding and core infrastructure are
              established.
            </p>
          </div>

          <section aria-labelledby="system-status-heading" className="space-y-3 pt-4 border-t border-slate-200 dark:border-slate-800">
            <h2
              id="system-status-heading"
              className="text-sm font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400"
            >
              System status
            </h2>
            <BackendStatus />
          </section>

          <div className="pt-4 border-t border-slate-200 dark:border-slate-800">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3">
              Phase 1 Deliverables
            </h2>
            <ul className="space-y-2 text-sm text-slate-600 dark:text-slate-400 list-disc list-inside">
              <li>Next.js + TypeScript frontend application shell</li>
              <li>Python + FastAPI backend service with health endpoint</li>
              <li>Containerized PostgreSQL database foundation</li>
              <li>Automated CI linting and testing pipelines</li>
            </ul>
          </div>
        </div>
      </main>

      <footer className="border-t border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 py-6">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-slate-500 dark:text-slate-400">
          <p>AI Travel Concierge — Travel Discovery and Planning Assistant.</p>
          <p>Phase 1 Foundation</p>
        </div>
      </footer>
    </div>
  );
}
