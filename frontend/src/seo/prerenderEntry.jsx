// Build-time entry used by scripts/prerender.mjs. Renders one route into the
// jsdom document, with the same providers as main.jsx, so each page's SeoHead
// and usePageTitle write its own <head> tags.
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { MemoryRouter } from "react-router-dom";
import App from "../App";
import { AuthProvider } from "../hooks/useAuth";
import { PageTitleProvider } from "../hooks/usePageTitle";
import { StateCodesProvider } from "../hooks/useStateCodes";
import { ThemeProvider } from "../hooks/useTheme";

export { programmaticRoutes } from "../lib/hsnData";

const tick = () => new Promise((r) => setTimeout(r, 0));

export async function renderRoute(pathname, container) {
  const root = createRoot(container);
  flushSync(() => {
    root.render(
      <ThemeProvider>
        <MemoryRouter initialEntries={[pathname]}>
          <PageTitleProvider>
            <StateCodesProvider>
              <AuthProvider>
                <App />
              </AuthProvider>
            </StateCodesProvider>
          </PageTitleProvider>
        </MemoryRouter>
      </ThemeProvider>,
    );
  });
  // Pages are lazy-loaded: wait for the Suspense skeletons to resolve, then let
  // passive effects (SeoHead's useEffect) run.
  for (let i = 0; i < 200 && container.querySelector('[aria-busy="true"]'); i++) {
    await new Promise((r) => setTimeout(r, 10));
  }
  for (let i = 0; i < 5; i++) await tick();
  return root;
}
