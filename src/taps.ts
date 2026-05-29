import { type Tap, createAtomValueTap } from '@owebeeone/grip-react';
import { grok } from './runtime';
import { COUNT, COUNT_TAP } from './grips';

export const CounterTap: Tap = createAtomValueTap(
  COUNT,
  { initial: COUNT.defaultValue ?? 0, handleGrip: COUNT_TAP },
) as unknown as Tap;

export function registerAllTaps() {
  grok.registerTap(CounterTap);
}
