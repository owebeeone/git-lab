import { readdirSync, readFileSync } from "node:fs";
import {
  TextWindowReassembler,
  parseTextWindowDelta,
  parseTextWindowSnapshot,
} from "../src/index.js";
import type { ResetEvent } from "../src/index.js";

function assert(condition: unknown, message: string): void {
  if (!condition) throw new Error(message);
}

function sameBytes(left: Uint8Array, right: Uint8Array): boolean {
  if (left.length !== right.length) return false;
  return left.every((value, index) => value === right[index]);
}

const fixtureRoot = new URL("../../../filedelta/fixtures/window_cases/", import.meta.url);
const cases = readdirSync(fixtureRoot).sort();

for (const caseName of cases) {
  const caseUrl = new URL(`${caseName}/`, fixtureRoot);
  const events = readFileSync(new URL("events.jsonl", caseUrl), "utf8")
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as Record<string, unknown>);
  const expectedBytes = readFileSync(new URL("expected-window.bin", caseUrl));
  const expectedText = readFileSync(new URL("expected-window.txt", caseUrl), "utf8");

  const reassembler = new TextWindowReassembler();
  for (const event of events) {
    if (event.type === "snapshot") {
      reassembler.applySnapshot(parseTextWindowSnapshot(event.snapshot));
    } else if (event.type === "delta") {
      reassembler.applyDelta(parseTextWindowDelta(event.delta));
    } else if (event.type === "reset") {
      const reset: ResetEvent = {
        type: "reset",
        reason: String(event.reason),
        seq: Number(event.seq),
        snapshot: parseTextWindowSnapshot(event.snapshot),
      };
      reassembler.applyReset(reset);
    } else {
      throw new Error(`unknown event type in ${caseName}`);
    }
  }

  assert(sameBytes(reassembler.bytes, expectedBytes), `${caseName}: expected bytes`);
  assert(reassembler.text === expectedText, `${caseName}: expected text`);
}
