import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import ErrorBoundary from "./components/ErrorBoundary";
import { AuthProvider } from "./hooks/useAuth";
import { PageTitleProvider } from "./hooks/usePageTitle";
import { StateCodesProvider } from "./hooks/useStateCodes";
import { ThemeProvider } from "./hooks/useTheme";
import "./index.css";

const fontCss = document.getElementById("font-css");
if (fontCss) {
  const sheet = document.createElement("link");
  sheet.rel = "stylesheet";
  sheet.href = fontCss.href;
  document.head.appendChild(sheet);
}

// Two boundaries, deliberately. This outer one is the last resort — it catches
// a crash in the Shell or the auth provider itself, where the inner per-page
// boundary has already been unmounted. Inside the router, because it resets on
// navigation and needs useLocation.
//
// PageTitleProvider sits outside that boundary rather than in: it owns the live
// region that announces route changes, and the one navigation most worth
// announcing is the one away from a screen that has just crashed.
//
// StateCodesProvider is above the router so its one fetch survives navigation
// between invoices, and inside the boundary because it holds no state worth
// keeping across a crash. It requests nothing until a screen asks it to.
ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <PageTitleProvider>
          <ErrorBoundary>
            <StateCodesProvider>
              <AuthProvider>
                <App />
              </AuthProvider>
            </StateCodesProvider>
          </ErrorBoundary>
        </PageTitleProvider>
      </BrowserRouter>
    </ThemeProvider>
  </React.StrictMode>,
);
