import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import Shell from "./components/Shell";
import { SkeletonPanel } from "./components/Skeleton";
import { useAuth } from "./hooks/useAuth";
import LandingPage from "./pages/LandingPage";
import ToolTracker from "./components/ToolTracker";
import SocialProofBar from "./components/SocialProofBar";

// The floating widgets are below the fold of every page and none of them is
// what the visitor came for, so they load after the route rather than sitting
// in the entry chunk every first paint has to download and parse.
const InstallPrompt = lazy(() => import("./components/InstallPrompt"));
const ReferralBanner = lazy(() => import("./components/ReferralBanner"));
const GstAdvisor = lazy(() => import("./components/GstAdvisor"));
const FeedbackWidget = lazy(() => import("./components/FeedbackWidget"));
const NotFoundPage = lazy(() => import("./pages/NotFoundPage"));

const AlertsPage = lazy(() => import("./pages/AlertsPage"));
const BlogLayout = lazy(() => import("./pages/BlogLayout"));
const BlogIndex = lazy(() => import("./pages/BlogLayout").then(m => ({ default: m.BlogIndex })));
const CalculatorPage = lazy(() => import("./pages/CalculatorPage"));
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const DueDatesPage = lazy(() => import("./pages/DueDatesPage"));
const EmbedPage = lazy(() => import("./pages/EmbedPage"));
const WidgetPage = lazy(() => import("./pages/WidgetPage"));
const FilingPage = lazy(() => import("./pages/FilingPage"));
const GstinPage = lazy(() => import("./pages/GstinPage"));
const GstRatePage = lazy(() => import("./pages/GstRatePage"));
const HsnFinderPage = lazy(() => import("./pages/HsnFinderPage"));
const InvoiceDetailPage = lazy(() => import("./pages/InvoiceDetailPage"));
const InvoicesPage = lazy(() => import("./pages/InvoicesPage"));
const ITCPage = lazy(() => import("./pages/ITCPage"));
const LookupPage = lazy(() => import("./pages/LookupPage"));
const PricingPage = lazy(() => import("./pages/PricingPage"));
const ReconcilePage = lazy(() => import("./pages/ReconcilePage"));
const ResourcesPage = lazy(() => import("./pages/ResourcesPage"));
const StatusPage = lazy(() => import("./pages/StatusPage"));
const SuppliersPage = lazy(() => import("./pages/SuppliersPage"));
const UploadPage = lazy(() => import("./pages/UploadPage"));
const UsagePage = lazy(() => import("./pages/UsagePage"));
const AuthCallbackPage = lazy(() => import("./pages/AuthCallbackPage"));
const LoginPage = lazy(() => import("./pages/LoginPage"));
const GstComplianceChecklist = lazy(() => import("./pages/blog/GstComplianceChecklist"));
const GstFilingGuide = lazy(() => import("./pages/blog/GstFilingGuide"));
const HsnCodeLookup = lazy(() => import("./pages/blog/HsnCodeLookup"));
const GstRegistrationOnline = lazy(() => import("./pages/blog/GstRegistrationOnline"));
const Gstr3bGuide = lazy(() => import("./pages/blog/Gstr3bGuide"));
const ItcReconciliationGuide = lazy(() => import("./pages/blog/ItcReconciliationGuide"));
const GstReturnCalendar = lazy(() => import("./pages/blog/GstReturnCalendar"));
const EInvoiceGuide = lazy(() => import("./pages/blog/EInvoiceGuide"));
const GstPenaltyGuide = lazy(() => import("./pages/blog/GstPenaltyGuide"));
const CompositionSchemeGuide = lazy(() => import("./pages/blog/CompositionSchemeGuide"));
const EwayBillBlogGuide = lazy(() => import("./pages/blog/EwayBillGuide"));
const Gstr1FilingStepByStep = lazy(() => import("./pages/blog/Gstr1FilingStepByStep"));
const GstRegistrationDocuments = lazy(() => import("./pages/blog/GstRegistrationDocuments"));
const Gstr1VsGstr3b = lazy(() => import("./pages/blog/Gstr1VsGstr3b"));
const CompositionVsRegular = lazy(() => import("./pages/blog/CompositionVsRegular"));
const HowToClaimItc = lazy(() => import("./pages/blog/HowToClaimItc"));
const GstRegistrationGuide2026 = lazy(() => import("./pages/blog/GstRegistrationGuide2026"));
const HsnCodeList2026 = lazy(() => import("./pages/blog/HsnCodeList2026"));
const Gst2ChangesExplained = lazy(() => import("./pages/blog/Gst2ChangesExplained"));
const GstReturnFilingOnline = lazy(() => import("./pages/blog/GstReturnFilingOnline"));
const GstRatesServices2026 = lazy(() => import("./pages/blog/GstRatesServices2026"));
const CgstSgstIgstDifference = lazy(() => import("./pages/blog/CgstSgstIgstDifference"));
const GstLatePenaltyCalculator = lazy(() => import("./pages/blog/GstLatePenaltyCalculator"));
const GstComplianceTipsSmallBusiness = lazy(() => import("./pages/blog/GstComplianceTipsSmallBusiness"));
const ReverseChargeGstGuide = lazy(() => import("./pages/blog/ReverseChargeGstGuide"));
const GstRegistrationProcess2026 = lazy(() => import("./pages/blog/GstRegistrationProcess2026"));
const Gstr3bCommonMistakes = lazy(() => import("./pages/blog/Gstr3bCommonMistakes"));
const ItcRules2026 = lazy(() => import("./pages/blog/ItcRules2026"));
const GstRateFinderGuide = lazy(() => import("./pages/blog/GstRateFinderGuide"));
const HowToFileNilGstReturn = lazy(() => import("./pages/blog/HowToFileNilGstReturn"));
const Gstr1Gstr3bMismatchFix = lazy(() => import("./pages/blog/Gstr1Gstr3bMismatchFix"));
const ClearTaxCompare = lazy(() => import("./pages/compare/ClearTaxCompare"));
const ZohoGstCompare = lazy(() => import("./pages/compare/ZohoGstCompare"));
const TallyCompare = lazy(() => import("./pages/compare/TallyCompare"));
const BusyCompare = lazy(() => import("./pages/compare/BusyCompare"));
const BestGstSoftwarePage = lazy(() => import("./pages/BestGstSoftwarePage"));
const BestGstTools = lazy(() => import("./pages/compare/BestGstTools"));
const GuidesIndex = lazy(() => import("./pages/guides/GuidesIndex"));
const GstRegistrationGuide = lazy(() => import("./pages/guides/GstRegistrationGuide"));
const Gstr1FilingGuide = lazy(() => import("./pages/guides/Gstr1FilingGuide"));
const Gstr3bFilingGuide = lazy(() => import("./pages/guides/Gstr3bFilingGuide"));
const InputTaxCreditGuide = lazy(() => import("./pages/guides/InputTaxCreditGuide"));
const EwayBillGuide = lazy(() => import("./pages/guides/EwayBillGuide"));
const PenaltyCalculatorPage = lazy(() => import("./pages/PenaltyCalculatorPage"));
const EwayBillPage = lazy(() => import("./pages/EwayBillPage"));
const ItcEligibilityPage = lazy(() => import("./pages/ItcEligibilityPage"));
const HsnCodePage = lazy(() => import("./pages/HsnCodePage"));
const CompositionSchemePage = lazy(() => import("./pages/CompositionSchemePage"));
const InvoiceGeneratorPage = lazy(() => import("./pages/InvoiceGeneratorPage"));
const ReverseChargePage = lazy(() => import("./pages/ReverseChargePage"));
const ItcMismatchPage = lazy(() => import("./pages/ItcMismatchPage"));
const RegistrationCheckerPage = lazy(() => import("./pages/RegistrationCheckerPage"));
const ReturnDueDateCalendarPage = lazy(() => import("./pages/ReturnDueDateCalendarPage"));
const InterestCalculatorPage = lazy(() => import("./pages/InterestCalculatorPage"));
const HsnSacFinderPage = lazy(() => import("./pages/HsnSacFinderPage"));
const GstinValidatorPage = lazy(() => import("./pages/GstinValidatorPage"));
const SchemeComparisonPage = lazy(() => import("./pages/SchemeComparisonPage"));
const PaymentChallanPage = lazy(() => import("./pages/PaymentChallanPage"));
const ItcCalculatorPage = lazy(() => import("./pages/ItcCalculatorPage"));
const RegistrationTypeAdvisorPage = lazy(() => import("./pages/RegistrationTypeAdvisorPage"));
const RCMCalculatorPage = lazy(() => import("./pages/RCMCalculatorPage"));
const AuditChecklistPage = lazy(() => import("./pages/AuditChecklistPage"));
const GstRegistrationProcessGuide = lazy(() => import("./pages/guides/GstRegistrationProcessGuide"));
const GstReturnCalendarGuide = lazy(() => import("./pages/guides/GstReturnCalendarGuide"));
const GstRatesListGuide = lazy(() => import("./pages/guides/GstRatesListGuide"));
const TurnoverLimitPage = lazy(() => import("./pages/TurnoverLimitPage"));
const LateFeeCalculatorPage = lazy(() => import("./pages/LateFeeCalculatorPage"));
const LateFeeInterestCalculatorPage = lazy(() => import("./pages/LateFeeInterestCalculatorPage"));
const Gstr9ChecklistPage = lazy(() => import("./pages/Gstr9ChecklistPage"));
const HsnWidgetPage = lazy(() => import("./pages/HsnWidgetPage"));
const Gst2RateComparisonPage = lazy(() => import("./pages/Gst2RateComparisonPage"));
const CompositionSchemeCheckerPage = lazy(() => import("./pages/CompositionSchemeCheckerPage"));
const Gst2MigrationCheckerPage = lazy(() => import("./pages/Gst2MigrationCheckerPage"));
const InsuranceSavingsPage = lazy(() => import("./pages/InsuranceSavingsPage"));
const Gst2GuidePage = lazy(() => import("./pages/guides/Gst2GuidePage"));
const ReferralPage = lazy(() => import("./pages/ReferralPage"));
const WhatsAppPage = lazy(() => import("./pages/WhatsAppPage"));
const Gstr2bReconciliationPage = lazy(() => import("./pages/Gstr2bReconciliationPage"));
const AdvisorPage = lazy(() => import("./pages/AdvisorPage"));
const TdsCalculatorPage = lazy(() => import("./pages/TdsCalculatorPage"));
const PlaceOfSupplyPage = lazy(() => import("./pages/PlaceOfSupplyPage"));
const RefundCalculatorPage = lazy(() => import("./pages/RefundCalculatorPage"));
const EInvoiceGeneratorPage = lazy(() => import("./pages/EInvoiceGeneratorPage"));
const Gstr9HelperPage = lazy(() => import("./pages/Gstr9HelperPage"));
const Gstr9SummaryPage = lazy(() => import("./pages/Gstr9SummaryPage"));
const ItcReconciliationDashboardPage = lazy(() => import("./pages/ItcReconciliationDashboardPage"));
const ReverseGstCalculatorPage = lazy(() => import("./pages/ReverseGstCalculatorPage"));
const Gstr9AnnualReturnGuide = lazy(() => import("./pages/blog/Gstr9AnnualReturnGuide"));
const GstImsGuide = lazy(() => import("./pages/blog/GstImsGuide"));
const GstOnGoldPage = lazy(() => import("./pages/GstOnGoldPage"));
const GstOnRealEstatePage = lazy(() => import("./pages/GstOnRealEstatePage"));
const GstOnRentalIncome = lazy(() => import("./pages/blog/GstOnRentalIncome"));
const GstRatesIndia2026List = lazy(() => import("./pages/blog/GstRatesIndia2026List"));

function LazyFallback() {
  return (
    <div className="shell-main">
      <SkeletonPanel lines={5} label="Loading" />
    </div>
  );
}

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="shell-main">
        <SkeletonPanel lines={5} label="Checking your session" />
      </div>
    );
  }
  if (!user) return <Navigate to="/" replace />;
  // Keyed on the tenant so switching GSTIN remounts the page and re-fetches
  // data rather than showing one business's numbers under another's name.
  return (
    <Shell>
      <ErrorBoundary key={user.business?.id ?? "home"}>
        <Suspense fallback={<LazyFallback />}>{children}</Suspense>
      </ErrorBoundary>
    </Shell>
  );
}

function Home() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="shell-main">
        <SkeletonPanel lines={5} label="Checking your session" />
      </div>
    );
  }
  if (!user) return <LandingPage />;
  return (
    <Shell>
      <ErrorBoundary key={user.business?.id ?? "home"}>
        <Suspense fallback={<LazyFallback />}>
          <DashboardPage />
        </Suspense>
      </ErrorBoundary>
    </Shell>
  );
}

function Lazy({ children }) {
  return <Suspense fallback={<LazyFallback />}>{children}</Suspense>;
}

// /login is the one public route whose content depends on the session: a
// signed-in visitor belongs on the dashboard, not over a sign-in form.
function LoginRoute() {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="shell-main">
        <SkeletonPanel lines={5} label="Checking your session" />
      </div>
    );
  }
  if (user) return <Navigate to="/" replace />;
  return <Lazy><LoginPage /></Lazy>;
}

export default function App() {
  return (
    <Suspense fallback={<LazyFallback />}>
      <ToolTracker />
      <SocialProofBar />
      <Routes>
        <Route path="/login" element={<LoginRoute />} />
        <Route path="/auth/callback" element={<Lazy><AuthCallbackPage /></Lazy>} />
        <Route path="/pricing" element={<Lazy><PricingPage /></Lazy>} />
        <Route path="/blog" element={<Lazy><BlogLayout /></Lazy>}>
          <Route index element={<Lazy><BlogIndex /></Lazy>} />
          <Route path="gst-filing-guide-india-2026" element={<Lazy><GstFilingGuide /></Lazy>} />
          <Route path="hsn-code-lookup" element={<Lazy><HsnCodeLookup /></Lazy>} />
          <Route path="gst-compliance-checklist-small-business" element={<Lazy><GstComplianceChecklist /></Lazy>} />
          <Route path="gst-registration-online-guide" element={<Lazy><GstRegistrationOnline /></Lazy>} />
          <Route path="gstr-3b-filing-guide" element={<Lazy><Gstr3bGuide /></Lazy>} />
          <Route path="itc-reconciliation-gstr-2a-guide" element={<Lazy><ItcReconciliationGuide /></Lazy>} />
          <Route path="gst-return-filing-calendar-2026-27" element={<Lazy><GstReturnCalendar /></Lazy>} />
          <Route path="e-invoice-under-gst-guide" element={<Lazy><EInvoiceGuide /></Lazy>} />
          <Route path="gst-penalties-interest-late-filing" element={<Lazy><GstPenaltyGuide /></Lazy>} />
          <Route path="gst-composition-scheme-guide" element={<Lazy><CompositionSchemeGuide /></Lazy>} />
          <Route path="eway-bill-gst-rules-guide" element={<Lazy><EwayBillBlogGuide /></Lazy>} />
          <Route path="how-to-file-gstr-1-step-by-step-2026" element={<Lazy><Gstr1FilingStepByStep /></Lazy>} />
          <Route path="gst-registration-documents-required-2026" element={<Lazy><GstRegistrationDocuments /></Lazy>} />
          <Route path="gstr-1-vs-gstr-3b-difference" element={<Lazy><Gstr1VsGstr3b /></Lazy>} />
          <Route path="composition-scheme-vs-regular-scheme" element={<Lazy><CompositionVsRegular /></Lazy>} />
          <Route path="how-to-claim-input-tax-credit-gst" element={<Lazy><HowToClaimItc /></Lazy>} />
          <Route path="gst-registration-complete-guide-2026" element={<Lazy><GstRegistrationGuide2026 /></Lazy>} />
          <Route path="hsn-code-list-2026-complete-guide" element={<Lazy><HsnCodeList2026 /></Lazy>} />
          <Route path="gst-2-changes-explained-india" element={<Lazy><Gst2ChangesExplained /></Lazy>} />
          <Route path="how-to-file-gst-returns-online" element={<Lazy><GstReturnFilingOnline /></Lazy>} />
          <Route path="gst-rates-services-2026" element={<Lazy><GstRatesServices2026 /></Lazy>} />
          <Route path="difference-between-cgst-sgst-igst" element={<Lazy><CgstSgstIgstDifference /></Lazy>} />
          <Route path="gst-late-filing-penalty-calculator" element={<Lazy><GstLatePenaltyCalculator /></Lazy>} />
          <Route path="gst-compliance-tips-small-business-2026" element={<Lazy><GstComplianceTipsSmallBusiness /></Lazy>} />
          <Route path="reverse-charge-mechanism-gst-guide-2026" element={<Lazy><ReverseChargeGstGuide /></Lazy>} />
          <Route path="gst-registration-process-step-by-step-2026" element={<Lazy><GstRegistrationProcess2026 /></Lazy>} />
          <Route path="gstr-3b-common-mistakes-how-to-avoid" element={<Lazy><Gstr3bCommonMistakes /></Lazy>} />
          <Route path="itc-rules-2026-what-every-business-must-know" element={<Lazy><ItcRules2026 /></Lazy>} />
          <Route path="gst-rate-finder-find-gst-rate-for-any-product" element={<Lazy><GstRateFinderGuide /></Lazy>} />
          <Route path="how-to-file-nil-gst-return-online-sms" element={<Lazy><HowToFileNilGstReturn /></Lazy>} />
          <Route path="gstr-1-vs-gstr-3b-mismatch-how-to-fix" element={<Lazy><Gstr1Gstr3bMismatchFix /></Lazy>} />
          <Route path="gstr-9-annual-return-fy-2025-26-guide" element={<Lazy><Gstr9AnnualReturnGuide /></Lazy>} />
          <Route path="gst-invoice-management-system-ims-guide" element={<Lazy><GstImsGuide /></Lazy>} />
          <Route path="gst-on-rental-income" element={<Lazy><GstOnRentalIncome /></Lazy>} />
          <Route path="gst-rates-india-2026-complete-list" element={<Lazy><GstRatesIndia2026List /></Lazy>} />
        </Route>
        <Route path="/calculator" element={<Lazy><CalculatorPage /></Lazy>} />
        <Route path="/lookup" element={<Lazy><LookupPage /></Lazy>} />
        <Route path="/hsn" element={<Lazy><HsnFinderPage /></Lazy>} />
        <Route path="/gstin/:gstin" element={<Lazy><GstinPage /></Lazy>} />
        <Route path="/gst-rate/:product" element={<Lazy><GstRatePage /></Lazy>} />
        <Route path="/due-dates" element={<Lazy><DueDatesPage /></Lazy>} />
        <Route path="/resources" element={<Lazy><ResourcesPage /></Lazy>} />
        <Route path="/compare/cleartax" element={<Lazy><ClearTaxCompare /></Lazy>} />
        <Route path="/compare/zoho-gst" element={<Lazy><ZohoGstCompare /></Lazy>} />
        <Route path="/compare/tally" element={<Lazy><TallyCompare /></Lazy>} />
        <Route path="/compare/busy" element={<Lazy><BusyCompare /></Lazy>} />
        <Route path="/best-gst-software" element={<Lazy><BestGstSoftwarePage /></Lazy>} />
        <Route path="/compare/best-gst-tools" element={<Lazy><BestGstTools /></Lazy>} />
        <Route path="/guides" element={<Lazy><GuidesIndex /></Lazy>} />
        <Route path="/guides/gst-registration" element={<Lazy><GstRegistrationGuide /></Lazy>} />
        <Route path="/guides/how-to-file-gstr-1" element={<Lazy><Gstr1FilingGuide /></Lazy>} />
        <Route path="/guides/how-to-file-gstr-3b" element={<Lazy><Gstr3bFilingGuide /></Lazy>} />
        <Route path="/guides/input-tax-credit" element={<Lazy><InputTaxCreditGuide /></Lazy>} />
        <Route path="/guides/eway-bill" element={<Lazy><EwayBillGuide /></Lazy>} />
        <Route path="/penalty-calculator" element={<Lazy><PenaltyCalculatorPage /></Lazy>} />
        <Route path="/eway-bill" element={<Lazy><EwayBillPage /></Lazy>} />
        <Route path="/input-tax-credit" element={<Lazy><ItcEligibilityPage /></Lazy>} />
        <Route path="/composition-scheme" element={<Lazy><CompositionSchemePage /></Lazy>} />
        <Route path="/invoice-generator" element={<Lazy><InvoiceGeneratorPage /></Lazy>} />
        <Route path="/reverse-charge" element={<Lazy><ReverseChargePage /></Lazy>} />
        <Route path="/itc-mismatch" element={<Lazy><ItcMismatchPage /></Lazy>} />
        <Route path="/gstin-validator" element={<Lazy><GstinValidatorPage /></Lazy>} />
        <Route path="/turnover-limit" element={<Lazy><TurnoverLimitPage /></Lazy>} />
        <Route path="/hsn/:code" element={<Lazy><HsnCodePage /></Lazy>} />
        <Route path="/registration-checker" element={<Lazy><RegistrationCheckerPage /></Lazy>} />
        <Route path="/return-calendar" element={<Lazy><ReturnDueDateCalendarPage /></Lazy>} />
        <Route path="/interest-calculator" element={<Lazy><InterestCalculatorPage /></Lazy>} />
        <Route path="/reverse-gst-calculator" element={<Lazy><ReverseGstCalculatorPage /></Lazy>} />
        <Route path="/gst-on-gold" element={<Lazy><GstOnGoldPage /></Lazy>} />
        <Route path="/gst-on-real-estate" element={<Lazy><GstOnRealEstatePage /></Lazy>} />
        <Route path="/hsn-sac-finder" element={<Lazy><HsnSacFinderPage /></Lazy>} />
        <Route path="/scheme-comparison" element={<Lazy><SchemeComparisonPage /></Lazy>} />
        <Route path="/payment-challan" element={<Lazy><PaymentChallanPage /></Lazy>} />
        <Route path="/itc-calculator" element={<Lazy><ItcCalculatorPage /></Lazy>} />
        <Route path="/registration-type-advisor" element={<Lazy><RegistrationTypeAdvisorPage /></Lazy>} />
        <Route path="/rcm-calculator" element={<Lazy><RCMCalculatorPage /></Lazy>} />
        <Route path="/audit-checklist" element={<Lazy><AuditChecklistPage /></Lazy>} />
        <Route path="/late-fee-calculator" element={<Lazy><LateFeeCalculatorPage /></Lazy>} />
        <Route path="/gst-late-fee-interest-calculator" element={<Lazy><LateFeeInterestCalculatorPage /></Lazy>} />
        <Route path="/gstr9-checklist" element={<Lazy><Gstr9ChecklistPage /></Lazy>} />
        <Route path="/gstr2b-reconciliation" element={<Lazy><Gstr2bReconciliationPage /></Lazy>} />
        <Route path="/guides/gst-registration-process" element={<Lazy><GstRegistrationProcessGuide /></Lazy>} />
        <Route path="/guides/gst-return-calendar-2026-27" element={<Lazy><GstReturnCalendarGuide /></Lazy>} />
        <Route path="/guides/gst-rates-list-2026" element={<Lazy><GstRatesListGuide /></Lazy>} />
        <Route path="/guides/gst-2-guide" element={<Lazy><Gst2GuidePage /></Lazy>} />
        <Route path="/rate-comparison" element={<Lazy><Gst2RateComparisonPage /></Lazy>} />
        <Route path="/tools/composition-scheme-checker" element={<Lazy><CompositionSchemeCheckerPage /></Lazy>} />
        <Route path="/migration-checker" element={<Lazy><Gst2MigrationCheckerPage /></Lazy>} />
        <Route path="/insurance-savings" element={<Lazy><InsuranceSavingsPage /></Lazy>} />
        <Route path="/referrals" element={<Lazy><ReferralPage /></Lazy>} />
        <Route path="/advisor" element={<Lazy><AdvisorPage /></Lazy>} />
        <Route path="/tds-calculator" element={<Lazy><TdsCalculatorPage /></Lazy>} />
        <Route path="/place-of-supply" element={<Lazy><PlaceOfSupplyPage /></Lazy>} />
        <Route path="/refund-calculator" element={<Lazy><RefundCalculatorPage /></Lazy>} />
        <Route path="/e-invoice-generator" element={<Lazy><EInvoiceGeneratorPage /></Lazy>} />
        <Route path="/gstr9-helper" element={<Lazy><Gstr9HelperPage /></Lazy>} />
        <Route path="/gstr9-summary" element={<Lazy><Gstr9SummaryPage /></Lazy>} />
        <Route path="/itc-reconciliation-dashboard" element={<Lazy><ItcReconciliationDashboardPage /></Lazy>} />
        <Route path="/whatsapp" element={<Lazy><WhatsAppPage /></Lazy>} />
        <Route path="/embed" element={<Lazy><EmbedPage /></Lazy>} />
        <Route path="/widget" element={<Lazy><WidgetPage /></Lazy>} />
        <Route path="/widget/hsn" element={<Lazy><HsnWidgetPage /></Lazy>} />
        <Route path="/" element={<Home />} />
        <Route
          path="/invoices"
          element={
            <Protected>
              <InvoicesPage />
            </Protected>
          }
        />
        <Route
          path="/invoices/:id"
          element={
            <Protected>
              <InvoiceDetailPage />
            </Protected>
          }
        />
        <Route
          path="/upload"
          element={
            <Protected>
              <UploadPage />
            </Protected>
          }
        />
        <Route
          path="/reconcile"
          element={
            <Protected>
              <ReconcilePage />
            </Protected>
          }
        />
        <Route
          path="/itc"
          element={
            <Protected>
              <ITCPage />
            </Protected>
          }
        />
        <Route
          path="/filing"
          element={
            <Protected>
              <FilingPage />
            </Protected>
          }
        />
        <Route
          path="/suppliers"
          element={
            <Protected>
              <SuppliersPage />
            </Protected>
          }
        />
        <Route
          path="/alerts"
          element={
            <Protected>
              <AlertsPage />
            </Protected>
          }
        />
        <Route
          path="/usage"
          element={
            <Protected>
              <UsagePage />
            </Protected>
          }
        />
        <Route
          path="/status"
          element={
            <Protected>
              <StatusPage />
            </Protected>
          }
        />
        <Route path="*" element={<Lazy><NotFoundPage /></Lazy>} />
      </Routes>
      <Suspense fallback={null}>
        <InstallPrompt />
        <ReferralBanner />
        <GstAdvisor />
        <FeedbackWidget />
      </Suspense>
    </Suspense>
  );
}
