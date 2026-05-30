import { GripProvider } from '@owebeeone/grip-react';
import { ClickReelProvider, ClickReelComplete, DEFAULT_PREFERENCES } from '@owebeeone/click-reel';
import { grok, main } from './runtime';

// Hide the Click Reel recorder by default; press Ctrl+Shift+R (toggleRecorder)
// to reveal it. We seed the preference only on first load so user changes stick.
const CR_PREF_KEY = 'click-reel-preferences';
if (typeof localStorage !== 'undefined' && !localStorage.getItem(CR_PREF_KEY)) {
  localStorage.setItem(CR_PREF_KEY, JSON.stringify({
    ...DEFAULT_PREFERENCES,
    recorderUI: { ...DEFAULT_PREFERENCES.recorderUI, showOnStartup: false },
  }));
}
import { registerAllTaps } from './taps';
import { registerLabMockTaps } from './lab/taps';
import { registerLabServiceTaps } from './lab/taps.service';
import ReactDOM from 'react-dom/client';
import App from './App';
import LabApp from './lab/LabApp';

// Dev flag: VITE_GL_UI selects which surface to render.
//   'lab'   (default) -> the grip-lab UI proposal mock
//   'hello'           -> the minimal starter app
const surface = (import.meta.env.VITE_GL_UI as string | undefined) ?? 'lab';
const dataMode = (import.meta.env.VITE_GL_DATA as string | undefined) ?? 'mock';

registerAllTaps();
if (dataMode === 'service') {
  registerLabServiceTaps();
} else {
  registerLabMockTaps();
}

const root = ReactDOM.createRoot(document.getElementById('root')!);
root.render(
  <GripProvider grok={grok} context={main}>
    <ClickReelProvider>
      {surface === 'hello' ? <App /> : <LabApp />}
      <ClickReelComplete />
    </ClickReelProvider>
  </GripProvider>
);
