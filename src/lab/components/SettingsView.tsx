import { useGrip } from '@owebeeone/grip-react';
import { THEME, THEME_TAP, UI_SCALE, UI_SCALE_TAP } from '../grips';
import type { ThemeId, UiScaleId } from '../types';

const THEMES: { id: ThemeId; label: string }[] = [
  { id: 'dark', label: 'Dark' },
  { id: 'light', label: 'Light' },
];

const UI_SCALES: { id: UiScaleId; label: string }[] = [
  { id: 'compact', label: 'Compact' },
  { id: 'standard', label: 'Standard' },
  { id: 'large', label: 'Large' },
];

export default function SettingsView() {
  const theme = useGrip(THEME) ?? 'dark';
  const themeTap = useGrip(THEME_TAP);
  const uiScale = useGrip(UI_SCALE) ?? 'standard';
  const uiScaleTap = useGrip(UI_SCALE_TAP);

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
      <div className="settings-group">
        <h3>UI Scale</h3>
        <div className="segmented">
          {UI_SCALES.map((t) => (
            <button
              key={t.id}
              className={uiScale === t.id ? 'active' : ''}
              onClick={() => uiScaleTap?.set(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
