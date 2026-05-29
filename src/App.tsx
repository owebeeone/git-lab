import { useGrip } from '@owebeeone/grip-react';
import { GREETING, COUNT, COUNT_TAP } from './grips';

export default function App() {
  const greeting = useGrip(GREETING);
  const count = useGrip(COUNT);
  const countTap = useGrip(COUNT_TAP);

  return (
    <main className="app">
      <h1>{greeting}</h1>
      <p className="subtitle">A minimal grip-react starter.</p>
      <div className="counter">
        <button onClick={() => countTap?.update((c) => (c ?? 0) - 1)}>-</button>
        <span className="count">{count}</span>
        <button onClick={() => countTap?.update((c) => (c ?? 0) + 1)}>+</button>
      </div>
    </main>
  );
}
