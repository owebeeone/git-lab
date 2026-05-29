import type { AtomTapHandle } from '@owebeeone/grip-react';
import { defineGrip } from './runtime';

export const GREETING = defineGrip<string>('Greeting', 'Hello, grip-lab!');

export const COUNT = defineGrip<number>('Count', 0);
export const COUNT_TAP = defineGrip<AtomTapHandle<number>>('Count.Tap');
