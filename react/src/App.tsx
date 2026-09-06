import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { QuizView } from "./views/QuizView";
import { MindmapView } from "./views/MindmapView";
import { FlashcardsView } from "./views/FlashcardsView";
import { ReportsView } from "./views/ReportsView";
import { SlidesView } from "./views/SlidesView";
import { DatatableView } from "./views/DatatableView";
import { InfographicView } from "./views/InfographicView";

/** One route per tkinter launcher. */
const ROUTES = [
  { path: "quizzes", label: "Quizzes", element: <QuizView /> },
  { path: "flashcards", label: "Flashcards", element: <FlashcardsView /> },
  { path: "mindmaps", label: "Mind maps", element: <MindmapView /> },
  { path: "reports", label: "Reports", element: <ReportsView /> },
  { path: "slides", label: "Slides", element: <SlidesView /> },
  { path: "datatables", label: "Data tables", element: <DatatableView /> },
  { path: "infographics", label: "Infographics", element: <InfographicView /> },
];

export function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1>Learning Content Viewers</h1>
        <nav>
          {ROUTES.map((route) => (
            <NavLink
              key={route.path}
              to={`/${route.path}`}
              className={({ isActive }) => (isActive ? "tab active" : "tab")}
            >
              {route.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <Routes>
        <Route path="/" element={<Navigate to="/quizzes" replace />} />
        {ROUTES.map((route) => (
          <Route key={route.path} path={`/${route.path}`} element={route.element} />
        ))}
        <Route path="*" element={<Navigate to="/quizzes" replace />} />
      </Routes>
    </div>
  );
}
