export function Logo({ size = 34 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      aria-hidden="true"
      className="logo-mark"
    >
      <circle cx="20" cy="20" r="18" stroke="currentColor" strokeOpacity="0.22" />
      <ellipse
        cx="20"
        cy="20"
        rx="18"
        ry="7.2"
        stroke="currentColor"
        strokeOpacity="0.45"
        transform="rotate(-28 20 20)"
      />
      <path
        d="M5.5 24.5c3.2-5.4 6.1 3.1 9.3-1.8 3.2-4.9 6.1 3.4 9.3-1.2 3.2-4.6 6.1 2.7 9.4-1.8"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
      />
      <circle cx="28.8" cy="13.4" r="2.1" fill="currentColor" />
    </svg>
  );
}
