import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import ErrorBoundary from "./components/ErrorBoundary";
import InstallPrompt from "./components/InstallPrompt";
import Shell from "./components/Shell";
import { SkeletonPanel } from "./components/Skeleton";
import { useAuth } from "./hooks/useAuth";
import LandingPage from "./pages/LandingPage";
import FeedbackWidget from "./components/FeedbackWidget";
import GstAdvisor from "./components/GstAdvisor";
import ToolTracker from "./components/ToolTracker";
import SocialProofBar from "./components/SocialProofBar";
import ReferralBanner from "./components/ReferralBanner";

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
      <ErrorBoundary key={user.business?.id ?? "home"}>{children}</ErrorBoundary>
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

export default function App() {
  return (
    <Suspense fallback={<LazyFallback />}>
      <ToolTracker />
      <SocialProofBar />
      <Routes>
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route path="/auth/callback" element={<AuthCallbackPage />} />
        <Route path="/pricing" element={<PricingPage />} />
        <Route path="/blog" element={<Lazy><BlogLayout /></Lazy>}>
          <Route index element={<Lazy><BlogIndex /></Lazy>} />
          <Route path="gst-filing-guide-india-2026" element={<GstFilingGuide />} />
          <Route path="hsn-code-lookup" element={<HsnCodeLookup />} />
          <Route path="gst-compliance-checklist-small-business" element={<GstComplianceChecklist />} />
          <Route path="gst-registration-online-guide" element={<GstRegistrationOnline />} />
          <Route path="gstr-3b-filing-guide" element={<Gstr3bGuide />} />
          <Route path="itc-reconciliation-gstr-2a-guide" element={<ItcReconciliationGuide />} />
          <Route path="gst-return-filing-calendar-2026-27" element={<GstReturnCalendar />} />
          <Route path="e-invoice-under-gst-guide" element={<EInvoiceGuide />} />
          <Route path="gst-penalties-interest-late-filing" element={<GstPenaltyGuide />} />
          <Route path="gst-composition-scheme-guide" element={<CompositionSchemeGuide />} />
          <Route path="eway-bill-gst-rules-guide" element={<EwayBillBlogGuide />} />
          <Route path="how-to-file-gstr-1-step-by-step-2026" element={<Gstr1FilingStepByStep />} />
          <Route path="gst-registration-documents-required-2026" element={<GstRegistrationDocuments />} />
          <Route path="gstr-1-vs-gstr-3b-difference" element={<Gstr1VsGstr3b />} />
          <Route path="composition-scheme-vs-regular-scheme" element={<CompositionVsRegular />} />
          <Route path="how-to-claim-input-tax-credit-gst" element={<HowToClaimItc />} />
          <Route path="gst-registration-complete-guide-2026" element={<GstRegistrationGuide2026 />} />
          <Route path="hsn-code-list-2026-complete-guide" element={<HsnCodeList2026 />} />
          <Route path="gst-2-changes-explained-india" element={<Gst2ChangesExplained />} />
          <Route path="how-to-file-gst-returns-online" element={<GstReturnFilingOnline />} />
          <Route path="gst-rates-services-2026" element={<GstRatesServices2026 />} />
          <Route path="difference-between-cgst-sgst-igst" element={<CgstSgstIgstDifference />} />
          <Route path="gst-late-filing-penalty-calculator" element={<GstLatePenaltyCalculator />} />
          <Route path="gst-compliance-tips-small-business-2026" element={<GstComplianceTipsSmallBusiness />} />
          <Route path="reverse-charge-mechanism-gst-guide-2026" element={<ReverseChargeGstGuide />} />
          <Route path="gst-registration-process-step-by-step-2026" element={<GstRegistrationProcess2026 />} />
          <Route path="gstr-3b-common-mistakes-how-to-avoid" element={<Gstr3bCommonMistakes />} />
          <Route path="itc-rules-2026-what-every-business-must-know" element={<ItcRules2026 />} />
          <Route path="gst-rate-finder-find-gst-rate-for-any-product" element={<GstRateFinderGuide />} />
          <Route path="how-to-file-nil-gst-return-online-sms" element={<HowToFileNilGstReturn />} />
          <Route path="gstr-1-vs-gstr-3b-mismatch-how-to-fix" element={<Gstr1Gstr3bMismatchFix />} />
        </Route>
        <Route path="/calculator" element={<CalculatorPage />} />
        <Route path="/lookup" element={<LookupPage />} />
        <Route path="/hsn" element={<HsnFinderPage />} />
        <Route path="/gstin/:gstin" element={<GstinPage />} />
        <Route path="/gst-rate/:product" element={<GstRatePage />} />
        <Route path="/due-dates" element={<DueDatesPage />} />
        <Route path="/resources" element={<ResourcesPage />} />
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
        <Route path="/hsn-sac-finder" element={<Lazy><HsnSacFinderPage /></Lazy>} />
        <Route path="/scheme-comparison" element={<Lazy><SchemeComparisonPage /></Lazy>} />
        <Route path="/payment-challan" element={<Lazy><PaymentChallanPage /></Lazy>} />
        <Route path="/itc-calculator" element={<Lazy><ItcCalculatorPage /></Lazy>} />
        <Route path="/registration-type-advisor" element={<Lazy><RegistrationTypeAdvisorPage /></Lazy>} />
        <Route path="/rcm-calculator" element={<Lazy><RCMCalculatorPage /></Lazy>} />
        <Route path="/audit-checklist" element={<Lazy><AuditChecklistPage /></Lazy>} />
        <Route path="/late-fee-calculator" element={<Lazy><LateFeeCalculatorPage /></Lazy>} />
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
        <Route path="/whatsapp" element={<Lazy><WhatsAppPage /></Lazy>} />
        <Route path="/embed" element={<EmbedPage />} />
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
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <InstallPrompt />
      <ReferralBanner />
      <GstAdvisor />
      <FeedbackWidget />
    </Suspense>
  );
}
