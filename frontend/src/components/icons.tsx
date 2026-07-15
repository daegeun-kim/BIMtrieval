// Minimal inline icon set (no icon-library dependency). Stroke icons at 1.6px
// to match the drafting/hairline aesthetic.
type IconProps = { size?: number; className?: string };

function Svg({ size = 16, className, children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

export const SendIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 12l15-7-6 16-3-6-6-3z" />
  </Svg>
);
export const CollapseIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 6l6 6-6 6" />
  </Svg>
);
export const ExpandIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M15 6l-6 6 6 6" />
  </Svg>
);
export const CloseIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Svg>
);
export const ResetIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
    <path d="M3 3v5h5" />
  </Svg>
);
export const BroomIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M19 5l-7 7" />
    <path d="M8 12l4 4-3 3H5v-4l3-3z" />
  </Svg>
);
export const HomeIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 11l8-6 8 6" />
    <path d="M6 10v9h12v-9" />
  </Svg>
);
export const StopIcon = (p: IconProps) => (
  <Svg {...p}>
    <rect x="7" y="7" width="10" height="10" rx="1.5" />
  </Svg>
);
