export default function BrandMark({ size = 28 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <rect width="24" height="24" rx="6" fill="#111827" />
      {["#0d9488", "#d97706", "#e11d48", "#7c3aed", "#0284c7", "#16a34a", "#db2777", "#ea580c", "#4f46e5"].map((color, i) => (
        <circle key={color} cx={5 + (i % 3) * 7} cy={5 + Math.floor(i / 3) * 7} r="2.3" fill={color} />
      ))}
    </svg>
  );
}
