import type { ResetEvent, TextWindowDelta, TextWindowSnapshot } from "./model.js";
import { hashBytes } from "./hash.js";
import { applyOps } from "./ops.js";

export class TextWindowReassembler {
  private snapshotValue: TextWindowSnapshot | null = null;
  private lastSeqValue = 0;

  get snapshot(): TextWindowSnapshot | null {
    return this.snapshotValue;
  }

  get bytes(): Uint8Array {
    if (!this.snapshotValue) throw new Error("no snapshot");
    return this.snapshotValue.data;
  }

  get text(): string {
    return new TextDecoder().decode(this.bytes);
  }

  applySnapshot(snapshot: TextWindowSnapshot): TextWindowSnapshot {
    this.snapshotValue = snapshot;
    this.lastSeqValue = 0;
    return snapshot;
  }

  applyDelta(delta: TextWindowDelta): TextWindowSnapshot {
    if (!this.snapshotValue) throw new Error("no base snapshot");
    if (delta.seq !== this.lastSeqValue + 1) {
      throw new Error("delta seq is not contiguous");
    }
    if (delta.baseFileVersion !== this.snapshotValue.fileVersion) {
      throw new Error("base file version mismatch");
    }
    if (delta.baseWindowVersion !== this.snapshotValue.windowVersion) {
      throw new Error("base window version mismatch");
    }
    if (delta.baseHash !== this.snapshotValue.contentHash) {
      throw new Error("base window hash mismatch");
    }

    const data = applyOps(this.snapshotValue.data, delta.ops);
    if (data.length !== delta.resultSize) {
      throw new Error("result size mismatch");
    }
    if (hashBytes(data) !== delta.resultHash) {
      throw new Error("result window hash mismatch");
    }

    this.snapshotValue = {
      scope: "text-window",
      resourceId: delta.resourceId,
      windowId: delta.windowId,
      fileVersion: delta.resultFileVersion,
      windowVersion: delta.resultWindowVersion,
      contentHash: delta.resultHash,
      kind: "content",
      lineStart: delta.lineStart,
      lineEnd: delta.lineEnd,
      totalLines: delta.totalLines,
      startByte: delta.startByte,
      endByte: delta.endByte,
      lineIndex: delta.lineIndex,
      truncated: delta.truncated,
      size: delta.resultSize,
      data,
      metadata: delta.metadata,
    };
    this.lastSeqValue = delta.seq;
    return this.snapshotValue;
  }

  applyReset(reset: ResetEvent): TextWindowSnapshot {
    if (reset.seq !== this.lastSeqValue + 1) {
      throw new Error("reset seq is not contiguous");
    }
    this.snapshotValue = reset.snapshot;
    this.lastSeqValue = reset.seq;
    return reset.snapshot;
  }
}
