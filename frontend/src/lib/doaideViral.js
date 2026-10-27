const STORAGE_KEY = 'doaide_recent_tools';

export function trackToolVisit(name, path) {
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    const filtered = stored.filter(t => t.path !== path);
    filtered.unshift({ name, path, ts: Date.now() });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(filtered.slice(0, 20)));
  } catch {}
}

export function getRecentTools(max = 5) {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]').slice(0, max);
  } catch {
    return [];
  }
}

// The seeded "daily count" and "daily rating" generators that used to live
// here are gone on purpose: social proof now comes from /meta/stats (see
// lib/usageStats.js) or is not shown at all.
export const TOOL_MAP = {
  '/calculator': 'GST Calculator',
  '/penalty-calculator': 'Penalty Calculator',
  '/late-fee-calculator': 'Late Fee Calculator',
  '/interest-calculator': 'Interest Calculator',
  '/itc-calculator': 'ITC Calculator',
  '/rcm-calculator': 'RCM Calculator',
  '/lookup': 'GSTIN Lookup',
  '/hsn': 'HSN Code Finder',
  '/hsn-sac-finder': 'HSN/SAC Finder',
  '/gstin-validator': 'GSTIN Validator',
  '/registration-checker': 'Registration Checker',
  '/input-tax-credit': 'ITC Eligibility',
  '/eway-bill': 'E-Way Bill Checker',
  '/reverse-charge': 'Reverse Charge',
  '/itc-mismatch': 'ITC Mismatch',
  '/audit-checklist': 'Audit Checklist',
  '/gstr9-checklist': 'GSTR-9 Checklist',
  '/composition-scheme': 'Composition Scheme',
  '/scheme-comparison': 'Scheme Comparison',
  '/due-dates': 'Due Dates Calendar',
  '/return-calendar': 'Return Calendar',
  '/invoice-generator': 'Invoice Generator',
  '/gstr2b-reconciliation': 'GSTR-2B Reconciliation',
  '/gstr3b-reconciliation': 'GSTR-3B Reconciliation',
  '/filing-checklist': 'Filing Checklist',
  '/payment-challan': 'Payment Challan',
  '/registration-type-advisor': 'Registration Advisor',
  '/turnover-limit': 'Turnover Limit',
  '/rate-comparison': 'GST 2.0 Rates',
  '/migration-checker': 'Migration Checker',
  '/insurance-savings': 'Insurance Savings',
};

export function trackReferral() {
  try {
    const params = new URLSearchParams(window.location.search);
    const ref = params.get('ref');
    if (!ref) return;

    if (ref === 'share') {
      const key = 'doaide_referral_count';
      const count = parseInt(localStorage.getItem(key) || '0', 10);
      localStorage.setItem(key, String(count + 1));
    } else if (ref.startsWith('CA-')) {
      fetch('/api/v1/referrals/track', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ referral_code: ref }),
      }).catch(() => {});
    }

    const url = new URL(window.location);
    url.searchParams.delete('ref');
    window.history.replaceState({}, '', url.pathname + url.search);
  } catch {}
}

export function getReferralCount() {
  try {
    return parseInt(localStorage.getItem('doaide_referral_count') || '0', 10);
  } catch { return 0; }
}

export function shouldShowReferralBanner() {
  try {
    const dismissed = localStorage.getItem('doaide_referral_dismissed');
    if (!dismissed) return true;
    return Date.now() - parseInt(dismissed, 10) > 7 * 24 * 60 * 60 * 1000;
  } catch { return true; }
}

export function dismissReferralBanner() {
  try {
    localStorage.setItem('doaide_referral_dismissed', String(Date.now()));
  } catch {}
}

export const TRENDING_TOOLS = [
  { name: 'Income Tax Calculator', url: 'https://tax.doaide.com/income-tax-calculator', product: 'TaxFile', icon: '🧮' },
  { name: 'Premium Calculator', url: 'https://insure.doaide.com/premium-calculator', product: 'InsureKit', icon: '₹' },
  { name: 'Resume Builder', url: 'https://resume.doaide.com', product: 'Resume', icon: '📝' },
  { name: 'Rent Receipt', url: 'https://docs.doaide.com/rent-receipt-generator', product: 'Docs', icon: '🏠' },
  { name: 'SIP Calculator', url: 'https://tax.doaide.com/sip-calculator', product: 'TaxFile', icon: '📈' },
  { name: 'Salary Slip', url: 'https://docs.doaide.com/salary-slip-generator', product: 'Docs', icon: '💰' },
  { name: 'EMI Calculator', url: 'https://tax.doaide.com/emi-calculator', product: 'TaxFile', icon: '🏠' },
  { name: 'Cover Letter', url: 'https://resume.doaide.com/cover-letter-generator', product: 'Resume', icon: '✉️' },
  { name: 'Plan Comparison', url: 'https://insure.doaide.com/compare-plans', product: 'InsureKit', icon: '⚖️' },
  { name: 'Invoice Generator', url: 'https://docs.doaide.com/invoice-generator', product: 'Docs', icon: '🧾' },
];
