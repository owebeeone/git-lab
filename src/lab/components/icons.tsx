// Dependency-free inline SVG icons (stroke = currentColor) so the tab bar and
// explorer have icons without pulling in an icon library.

export function Icon({ name, size = 16 }: { name: string; size?: number }) {
  const common = {
    width: size, height: size, viewBox: '0 0 24 24', fill: 'none',
    stroke: 'currentColor', strokeWidth: 1.8,
    strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const,
  };
  switch (name) {
    case 'workspace':
      return (
        <svg {...common}>
          <rect x="3" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" />
          <rect x="14" y="14" width="7" height="7" rx="1" />
        </svg>
      );
    case 'files':
      return (
        <svg {...common}>
          <path d="M14 3v5h5" />
          <path d="M7 3h7l5 5v11a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
        </svg>
      );
    case 'diff':
      return (
        <svg {...common}>
          <path d="M12 3v18" />
          <rect x="3" y="6" width="6" height="6" rx="1" />
          <rect x="15" y="12" width="6" height="6" rx="1" />
        </svg>
      );
    case 'collaborators':
      return (
        <svg {...common}>
          <circle cx="9" cy="8" r="3" />
          <path d="M3 20c0-3 2.7-5 6-5s6 2 6 5" />
          <path d="M16 5.5a3 3 0 0 1 0 6" />
          <path d="M21.5 20c0-2.2-1.4-3.8-3.5-4.3" />
        </svg>
      );
    case 'settings':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 13a7.6 7.6 0 0 0 0-2l2-1.5-2-3.5-2.4 1a7.6 7.6 0 0 0-1.7-1L14.9 3h-3.8l-.4 2.5a7.6 7.6 0 0 0-1.7 1l-2.4-1-2 3.5L4.6 11a7.6 7.6 0 0 0 0 2l-2 1.5 2 3.5 2.4-1a7.6 7.6 0 0 0 1.7 1l.4 2.5h3.8l.4-2.5a7.6 7.6 0 0 0 1.7-1l2.4 1 2-3.5z" />
        </svg>
      );
    case 'folder':
      return (
        <svg {...common}>
          <path d="M3 7a1 1 0 0 1 1-1h5l2 2h8a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" />
        </svg>
      );
    case 'file':
      return (
        <svg {...common}>
          <path d="M14 3v5h5" />
          <path d="M7 3h7l5 5v11a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
        </svg>
      );
    case 'chevron':
      return (
        <svg {...common}><path d="M9 6l6 6-6 6" /></svg>
      );
    default:
      return null;
  }
}
