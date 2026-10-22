/**
 * Inncos simgesi: yuvarlak köşeli kare içinde damla ve köpük kabarcığı (favicon ile aynı biçim).
 * `inverse` koyu zemin içindir: beyaz kare, mavi damla.
 */
export function BrandMark({ size = 40, inverse = false }: { size?: number; inverse?: boolean }) {
  const box = inverse ? "#ffffff" : "#1c7ed6";
  const drop = inverse ? "#1c7ed6" : "#ffffff";
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="8" fill={box} />
      <path d="M15 6c-4 6-7 9.5-7 13a7 7 0 0 0 14 0c0-3.5-3-7-7-13z" fill={drop} />
      <circle cx="23.5" cy="9" r="2.6" fill="none" stroke={drop} strokeWidth="1.4" opacity="0.85" />
    </svg>
  );
}
