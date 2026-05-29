import { useGrip } from '@owebeeone/grip-react';
import { THEME, THEME_TAP } from '../grips';
import type { ThemeId } from '../types';

const THEMES: { id: ThemeId; label: string }[] = [
  { id: 'dark', label: 'Dark' },
  { id: 'light', label: 'Light' },
];

export default function SettingsView() {
  const theme = useGrip(THEME) ?? 'dark';
  const themeTap = useGrip(THEME_TAP);

  return (
    <section className="view">
      <div className="settings-group">
        <h3>Theme</h3>
        <div className="segmented">
          {THEMES.map((t) => (
            <button
              key={t.id}
              className={theme === t.id ? 'active' : ''}
              onClick={() => themeTap?.set(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
