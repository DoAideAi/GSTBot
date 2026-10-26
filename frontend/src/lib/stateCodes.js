// GST state codes for the public reference page (/gst-state-codes).
//
// The server's STATE_CODES (backend/app/services/gstin.py) is what decides
// whether a GSTIN is valid, and forms fetch it through useStateCodes. This copy
// exists only because a page meant for search engines has to carry the list in
// its prerendered HTML, where no request runs. stateCodes.test.js reads the
// backend file and fails if the two disagree.
//
// `tax` is what an intra-state supply carries alongside CGST: SGST in states
// and in the union territories with a legislature (Delhi, Puducherry, Jammu and
// Kashmir), UTGST in the other union territories.

export const STATE_CODES = [
  { code: "01", name: "Jammu and Kashmir", kind: "Union territory", tax: "SGST" },
  { code: "02", name: "Himachal Pradesh", kind: "State", tax: "SGST" },
  { code: "03", name: "Punjab", kind: "State", tax: "SGST" },
  { code: "04", name: "Chandigarh", kind: "Union territory", tax: "UTGST" },
  { code: "05", name: "Uttarakhand", kind: "State", tax: "SGST" },
  { code: "06", name: "Haryana", kind: "State", tax: "SGST" },
  { code: "07", name: "Delhi", kind: "Union territory", tax: "SGST" },
  { code: "08", name: "Rajasthan", kind: "State", tax: "SGST" },
  { code: "09", name: "Uttar Pradesh", kind: "State", tax: "SGST" },
  { code: "10", name: "Bihar", kind: "State", tax: "SGST" },
  { code: "11", name: "Sikkim", kind: "State", tax: "SGST" },
  { code: "12", name: "Arunachal Pradesh", kind: "State", tax: "SGST" },
  { code: "13", name: "Nagaland", kind: "State", tax: "SGST" },
  { code: "14", name: "Manipur", kind: "State", tax: "SGST" },
  { code: "15", name: "Mizoram", kind: "State", tax: "SGST" },
  { code: "16", name: "Tripura", kind: "State", tax: "SGST" },
  { code: "17", name: "Meghalaya", kind: "State", tax: "SGST" },
  { code: "18", name: "Assam", kind: "State", tax: "SGST" },
  { code: "19", name: "West Bengal", kind: "State", tax: "SGST" },
  { code: "20", name: "Jharkhand", kind: "State", tax: "SGST" },
  { code: "21", name: "Odisha", kind: "State", tax: "SGST" },
  { code: "22", name: "Chhattisgarh", kind: "State", tax: "SGST" },
  { code: "23", name: "Madhya Pradesh", kind: "State", tax: "SGST" },
  { code: "24", name: "Gujarat", kind: "State", tax: "SGST" },
  { code: "25", name: "Daman and Diu", kind: "Union territory (merged into 26 in 2020)", tax: "UTGST" },
  { code: "26", name: "Dadra and Nagar Haveli and Daman and Diu", kind: "Union territory", tax: "UTGST" },
  { code: "27", name: "Maharashtra", kind: "State", tax: "SGST" },
  { code: "28", name: "Andhra Pradesh (before division)", kind: "State (pre-2014 code)", tax: "SGST" },
  { code: "29", name: "Karnataka", kind: "State", tax: "SGST" },
  { code: "30", name: "Goa", kind: "State", tax: "SGST" },
  { code: "31", name: "Lakshadweep", kind: "Union territory", tax: "UTGST" },
  { code: "32", name: "Kerala", kind: "State", tax: "SGST" },
  { code: "33", name: "Tamil Nadu", kind: "State", tax: "SGST" },
  { code: "34", name: "Puducherry", kind: "Union territory", tax: "SGST" },
  { code: "35", name: "Andaman and Nicobar Islands", kind: "Union territory", tax: "UTGST" },
  { code: "36", name: "Telangana", kind: "State", tax: "SGST" },
  { code: "37", name: "Andhra Pradesh", kind: "State", tax: "SGST" },
  { code: "38", name: "Ladakh", kind: "Union territory", tax: "UTGST" },
  { code: "97", name: "Other Territory", kind: "Offshore areas outside any state", tax: null },
  { code: "99", name: "Centre Jurisdiction", kind: "Centre-registered (e.g. OIDAR, UN bodies)", tax: null },
];

/** The state entry for a GSTIN or a bare 2-digit code, or null. */
export function stateForGstin(input) {
  const code = (input || "").trim().slice(0, 2);
  if (!/^\d{2}$/.test(code)) return null;
  return STATE_CODES.find((s) => s.code === code) || null;
}
